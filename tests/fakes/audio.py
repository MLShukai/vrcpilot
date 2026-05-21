"""Audio-related test doubles.

Two thin stand-ins:

* :class:`FakeSpeaker` mirrors the public
  :class:`vrcpilot.speaker.session.Speaker` surface (``read`` / ``close``
  / context manager). Used by :class:`vrcpilot.speaker.loop.SpeakerLoop`
  tests where the loop's threading machinery is exercised against a
  deterministic chunk source.

* :class:`FakeProcessAudioCapture` mirrors the
  :class:`proctap.ProcessAudioCapture` surface that
  :class:`vrcpilot.speaker.proctap.ProcTapSpeakerBackend` actually
  invokes (``start`` / ``stop`` / ``close`` / ``read(timeout)``). The
  backend exposes a single factory method, ``_open_capture``, that the
  production path overrides to call ``proctap``. Tests patch that
  factory to return a :class:`FakeProcessAudioCapture` so the
  ``read`` / ``close`` paths can be exercised without touching real
  audio hardware.

The fakes only implement methods production actually calls; the
``feedback_fakes_mirror_production`` rule in the project memory
applies.
"""

from __future__ import annotations

import time
from collections import deque
from types import TracebackType
from typing import Self

import numpy as np
from numpy.typing import NDArray

from vrcpilot.speaker.base import CHANNELS


class FakeProcessAudioCapture:
    """Duck-typed stand-in for :class:`proctap.ProcessAudioCapture`.

    Backed by an in-memory FIFO of ``bytes`` chunks (proc-tap's native
    return type). ``emit_samples`` queues one chunk in float32 ndarray
    form and converts it to interleaved bytes the way proc-tap does;
    tests can also push raw bytes via :attr:`enqueue_bytes` when they
    need to drive the truncation branch of the backend.
    """

    def __init__(self, *, pid: int) -> None:
        self.pid = pid
        self.start_calls: int = 0
        self.stop_calls: int = 0
        self.close_calls: int = 0
        self.read_calls: int = 0
        self.stop_raises: BaseException | None = None
        self.close_raises: BaseException | None = None
        self._queue: deque[bytes] = deque()

    def emit_samples(self, samples: NDArray[np.float32]) -> None:
        """Queue ``samples`` (shape ``(N, CHANNELS)``) as one proc-tap chunk.

        The samples are flattened to interleaved float32 little-endian
        bytes, which is the format proc-tap delivers on Windows.
        """
        if samples.ndim != 2 or samples.shape[1] != CHANNELS:
            raise ValueError(
                f"emit_samples expects shape (N, {CHANNELS}), got {samples.shape}"
            )
        if samples.dtype != np.float32:
            raise ValueError(f"emit_samples expects float32, got dtype={samples.dtype}")
        self._queue.append(samples.tobytes())

    def enqueue_bytes(self, payload: bytes) -> None:
        """Queue a raw byte payload (advanced; bypasses shape checks)."""
        self._queue.append(payload)

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1
        if self.stop_raises is not None:
            raise self.stop_raises

    def close(self) -> None:
        self.close_calls += 1
        if self.close_raises is not None:
            raise self.close_raises

    def read(self, timeout: float) -> bytes | None:
        """Pop the next queued chunk or ``None`` if the queue is empty.

        ``timeout`` is accepted for signature parity with proc-tap; the
        fake never blocks because tests load the queue synchronously.
        """
        del timeout
        self.read_calls += 1
        if not self._queue:
            return None
        return self._queue.popleft()


class FakeSpeaker:
    """Stand-in for :class:`vrcpilot.speaker.session.Speaker`.

    Used in :class:`vrcpilot.speaker.loop.SpeakerLoop` tests where the
    OS-level proc-tap backend is irrelevant but the loop's own threading
    machinery still needs to be exercised against a real, deterministic
    chunk source.

    Constructor arguments mirror :class:`vrcpilot.Speaker` so the fake
    can be substituted via either ``mocker.patch(..., FakeSpeaker)``
    (replace the class) or ``mocker.patch(..., return_value=fake)``
    (replace the instance).

    Args:
        read_timeout: Accepted for signature compatibility; recorded as
            :attr:`read_timeout` so tests can assert forwarding.
        read_side_effect: Raised from :meth:`read` instead of returning
            a chunk. ``None`` (default) returns a zero-length chunk.
        read_delay: Sleep injected before each :meth:`read` returns,
            useful for pacing tests.
        chunk: ndarray returned from :meth:`read`. Default is an empty
            ``(0, CHANNELS)`` array so tests can assert empty-chunk
            forwarding without setting anything up.
    """

    def __init__(
        self,
        *,
        read_timeout: float = 2.0,
        read_side_effect: BaseException | None = None,
        read_delay: float = 0.0,
        chunk: NDArray[np.float32] | None = None,
    ) -> None:
        self.read_timeout = read_timeout
        self.read_calls: int = 0
        self.close_calls: int = 0
        self._read_side_effect = read_side_effect
        self._read_delay = read_delay
        self._chunk = (
            chunk if chunk is not None else np.zeros((0, CHANNELS), dtype=np.float32)
        )

    def read(self) -> NDArray[np.float32]:
        self.read_calls += 1
        if self._read_delay > 0:
            time.sleep(self._read_delay)
        if self._read_side_effect is not None:
            raise self._read_side_effect
        return self._chunk

    def close(self) -> None:
        self.close_calls += 1

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
