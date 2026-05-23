"""Background-thread driver that paces :class:`Capture` reads at a fixed FPS.

Kept separate from :class:`Capture` so one-shot ``read()`` callers do
not pay for thread machinery.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import Self

import numpy as np

from .session import Capture

type FrameCallback = Callable[[np.ndarray], None]


class CaptureLoop:
    """Run a :class:`Capture` on a background thread at a fixed FPS.

    The loop is deadline-based (drift-resistant) and uses an
    :class:`threading.Event` sleep so :meth:`stop` wakes the worker
    promptly. ``frame_timeout`` and ``pid`` are forwarded to the owned
    :class:`Capture`; startup failures (VRChat not running, multiple
    instances without an explicit ``pid``, unsupported platform, etc.)
    propagate from it unchanged.

    Raises:
        ValueError: ``fps`` is not strictly positive.
    """

    _capture: Capture
    _callback: FrameCallback
    _fps: float
    _stop_event: threading.Event
    _thread: threading.Thread | None
    _closed: bool
    _exception: BaseException | None
    _lock: threading.Lock

    def __init__(
        self,
        callback: FrameCallback,
        *,
        fps: float,
        frame_timeout: float = 2.0,
        pid: int | None = None,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be > 0")

        self._callback = callback
        self._fps = fps
        self._stop_event = threading.Event()
        self._thread = None
        self._closed = False
        self._exception = None
        self._lock = threading.Lock()
        # Capture last so a ValueError above does not leak a backend.
        self._capture = Capture(frame_timeout=frame_timeout, pid=pid)

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
                raise RuntimeError("CaptureLoop is closed")
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("CaptureLoop is already running")
            self._stop_event.clear()
            self._exception = None
            self._thread = threading.Thread(
                target=self._run,
                name="CaptureLoop",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Signal the worker to stop and join it.

        Idempotent. Re-raises any exception caught from the background
        thread (callback or :meth:`Capture.read` failure) and clears it
        so subsequent calls do not raise twice. Safe to call from inside
        the callback - the self-join is skipped to avoid deadlock.
        """
        with self._lock:
            self._stop_event.set()
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join()
                self._thread = None
            # Same-thread case (callback called stop()): skip join to
            # avoid self-deadlock and leave _thread set so is_running
            # stays truthful while the caller's frame is still on the
            # stack; _run will exit once control returns to it.
            # thread is None case: already stopped or never started.

            exc = self._exception
            self._exception = None

        if exc is not None:
            raise exc

    def close(self) -> None:
        """Stop the loop and release the underlying :class:`Capture`.

        Idempotent. Does not swallow exceptions surfaced by :meth:`stop`.
        """
        if self._closed:
            return
        try:
            self.stop()
        finally:
            self._closed = True
            self._capture.close()

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
        interval = 1.0 / self._fps
        next_deadline = time.perf_counter()
        try:
            while not self._stop_event.is_set():
                frame = self._capture.read()
                self._callback(frame)
                next_deadline += interval
                sleep_for = next_deadline - time.perf_counter()
                if sleep_for > 0:
                    if self._stop_event.wait(sleep_for):
                        break
                else:
                    # Callback overran the budget; resync deadline so we
                    # do not burn CPU trying to "catch up".
                    next_deadline = time.perf_counter()
        except BaseException as exc:  # noqa: BLE001 - intentional, surfaced via stop()
            self._exception = exc
