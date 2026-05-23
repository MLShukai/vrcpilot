"""Background-thread driver that pumps :class:`Speaker` reads to a callback."""

from __future__ import annotations

import threading
from collections.abc import Callable
from types import TracebackType
from typing import Self

import numpy as np
from numpy.typing import NDArray

from vrcpilot.speaker.session import Speaker

type AudioCallback = Callable[[NDArray[np.float32]], None]


class SpeakerLoop:
    """Run a :class:`Speaker` on a background thread.

    Constructs and owns its own :class:`Speaker`; VRChat must already
    be running. Each tick drains one chunk and forwards it to
    ``callback``. Empty chunks (``N == 0``) are forwarded verbatim as a
    "silence tick" signal. Exceptions from the callback or
    :meth:`Speaker.read` are stashed and re-raised on the next
    :meth:`stop` / :meth:`close` so the worker never dies silently.

    ``chunk_seconds`` is the inter-tick sleep, in seconds.

    Args:
        callback: Invoked with each ndarray ``Speaker.read`` returns.
        chunk_seconds: Inter-tick sleep budget; must be ``> 0``.
        read_timeout: Forwarded to the owned :class:`Speaker`; must be
            ``> 0``.
        pid: Target VRChat PID forwarded to :class:`Speaker`. When
            omitted, :func:`vrcpilot.process.resolve_pid` picks the sole
            running instance and raises
            :class:`vrcpilot.process.VRChatMultipleInstancesError` if
            more than one VRChat process is running.

    Raises:
        RuntimeError: The internal :class:`Speaker` cannot start.
        ValueError: ``chunk_seconds`` or ``read_timeout`` is not
            strictly positive.
        VRChatMultipleInstancesError: ``pid`` omitted and multiple
            instances are running.
    """

    _speaker: Speaker
    _callback: AudioCallback
    _chunk_seconds: float
    _stop_event: threading.Event
    _thread: threading.Thread | None
    _closed: bool
    _exception: BaseException | None
    _lock: threading.Lock

    def __init__(
        self,
        callback: AudioCallback,
        *,
        chunk_seconds: float = 0.05,
        read_timeout: float = 2.0,
        pid: int | None = None,
    ) -> None:
        if chunk_seconds <= 0:
            raise ValueError(f"chunk_seconds must be > 0 (got {chunk_seconds})")

        self._callback = callback
        self._chunk_seconds = chunk_seconds
        self._stop_event = threading.Event()
        self._thread = None
        self._closed = False
        self._exception = None
        self._lock = threading.Lock()
        # Speaker last so a ValueError above does not leak a backend.
        self._speaker = Speaker(read_timeout=read_timeout, pid=pid)

    @property
    def is_running(self) -> bool:
        """``True`` while the worker thread is alive."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """Start the worker thread.

        Raises:
            RuntimeError: Loop is already running or has been closed.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("SpeakerLoop is closed")
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("SpeakerLoop is already running")
            self._stop_event.clear()
            self._exception = None
            self._thread = threading.Thread(
                target=self._run,
                name="SpeakerLoop",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Signal the worker to stop and join it.

        Idempotent. Re-raises any exception captured from the worker
        once, then clears it. Safe to call from inside the callback: the
        self-join is skipped to avoid deadlock and the worker exits when
        control returns to its own frame.
        """
        with self._lock:
            self._stop_event.set()
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join()
                self._thread = None
            # Same-thread case (callback called stop()): skip join to
            # avoid self-deadlock. thread is None case: already stopped
            # or never started.

            exc = self._exception
            self._exception = None

        if exc is not None:
            raise exc

    def close(self) -> None:
        """Stop the loop and release the underlying :class:`Speaker`.

        Idempotent. Does not swallow exceptions surfaced by
        :meth:`stop`; callers must be able to observe worker failures
        even when they only called :meth:`close`.
        """
        if self._closed:
            return
        try:
            self.stop()
        finally:
            self._closed = True
            self._speaker.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                chunk = self._speaker.read()
                self._callback(chunk)
                # Use ``Event.wait`` so stop() interrupts the sleep
                # immediately. Returning ``True`` means the event was
                # set during the wait -> exit promptly.
                if self._stop_event.wait(self._chunk_seconds):
                    break
        except BaseException as exc:  # noqa: BLE001 - intentional, surfaced via stop()
            self._exception = exc
