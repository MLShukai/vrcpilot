"""Public :class:`Capture` session and platform backend selection."""

from __future__ import annotations

import sys
from types import TracebackType
from typing import Self

import numpy as np

from .base import CaptureBackend


def _select_capture_backend(*, frame_timeout: float) -> CaptureBackend:
    """Return the platform-appropriate :class:`CaptureBackend`.

    Imports the chosen backend lazily so platform-specific dependencies
    (``windows_capture`` on Windows, ``Xlib`` on Linux) never need to be
    importable on the other platform.
    """
    if sys.platform == "win32":
        from .windows import Win32CaptureBackend

        return Win32CaptureBackend(frame_timeout=frame_timeout)
    if sys.platform == "linux":
        from .linux import X11CaptureBackend

        return X11CaptureBackend()
    raise NotImplementedError(f"Capture is not supported on {sys.platform}")


class Capture:
    """Continuous-frame capture session for the VRChat window.

    The session is single-use: a single backend connection is held open
    until :meth:`close`, and reads are latest-only — old frames buffered
    while the consumer was busy are discarded so lag cannot accumulate
    when the consumer falls behind. Callers that need every frame must
    drive :meth:`read` faster than the producer.

    Args:
        frame_timeout: Seconds :meth:`read` will wait for a frame before
            raising :class:`TimeoutError`. Must be ``> 0``. Default
            ``2.0`` is generous for WGC's ~33 ms cadence.

    Raises:
        NotImplementedError: Platform other than Windows or Linux.
        RuntimeError: Backend cannot start (VRChat not running, window
            not mapped, X11 display unavailable, Composite missing, WGC
            session failed, or native Wayland — streaming has no useful
            fallback there).
        ValueError: ``frame_timeout`` is not strictly positive.
    """

    _backend: CaptureBackend
    _closed: bool

    def __init__(self, *, frame_timeout: float = 2.0) -> None:
        if frame_timeout <= 0:
            raise ValueError("frame_timeout must be > 0")

        self._closed = False
        self._backend = _select_capture_backend(frame_timeout=frame_timeout)

    def read(self) -> np.ndarray:
        """Return the latest unread frame as an ``(H, W, 3)`` uint8 RGB
        ndarray.

        Latest-only: any frame produced while the consumer was busy is
        discarded so lag cannot accumulate. The returned array is
        detached from internal buffers (safe to retain and mutate), and
        its shape may change across calls if the window is resized.

        Raises:
            RuntimeError: Capture is closed or the backend reports a fatal error.
            TimeoutError: No frame within ``frame_timeout`` seconds
                (Windows / WGC only; the X11 path is synchronous).
        """
        if self._closed:
            raise RuntimeError("Capture is closed")
        return self._backend.read()

    def close(self) -> None:
        """Release the backend; idempotent and never raises.

        Backend cleanup failures are surfaced as :class:`RuntimeWarning`
        so ``__exit__`` paths stay safe.
        """
        if self._closed:
            return
        self._closed = True
        self._backend.close()

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
