"""Windows.Graphics.Capture backend for :class:`vrcpilot.Capture`.

The ``windows_capture`` library is free-threaded: it fires
``on_frame_arrived`` from a worker thread, so the latest frame is
stashed in a single-slot, lock-protected buffer.
"""

from __future__ import annotations

import sys

if sys.platform != "win32":
    raise ImportError

import threading
import warnings
from typing import Any, cast, override

import numpy as np

# ``windows_capture`` ships no type stubs (it's a thin wrapper over a
# PyO3 native module). The import itself trips ``reportMissingTypeStubs``,
# which we silence explicitly here. We then re-bind the symbol with an
# ``Any`` annotation so every downstream attribute read, decorator use,
# and constructor call inherits ``Any`` instead of needing its own
# ``reportUnknown*`` suppression. The public name ``WindowsCapture`` is
# preserved because tests patch the module attribute by that name.
from windows_capture import (  # pyright: ignore[reportMissingTypeStubs]
    WindowsCapture as _WindowsCaptureRaw,
)

from vrcpilot.windows import find_vrchat_hwnd

from .base import CaptureBackend

WindowsCapture: Any = _WindowsCaptureRaw


class Win32CaptureBackend(CaptureBackend):
    """WGC-backed capture session.

    The single-slot latest-only buffer caps worst-case staleness at one
    frame interval — a FIFO would let lag accumulate when consumers fall
    behind.
    """

    _frame_timeout: float
    _closed: bool
    _latest_frame: tuple[np.ndarray, int, int] | None
    _frame_lock: threading.Lock
    _frame_event: threading.Event
    _control: object  # ``windows_capture.CaptureControl`` (no stubs).

    def __init__(self, *, frame_timeout: float, pid: int) -> None:
        self._frame_timeout = frame_timeout
        self._closed = False

        hwnd = find_vrchat_hwnd(pid)
        if hwnd is None:
            raise RuntimeError("VRChat top-level window is not yet mapped")

        # Single-slot latest-frame buffer; threading.Event wakes ``read``.
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._frame_event = threading.Event()

        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_hwnd=hwnd,
        )

        def on_frame_arrived(frame: Any, control: Any) -> None:
            del control  # We never stop from inside the handler.
            # ``frame.frame_buffer`` is a row-tight ``(H, W, 4)`` BGRA ndarray;
            # the library has already collapsed the GPU stride for us. Convert
            # BGRA -> RGB and copy out so the buffer is safe to keep after the
            # handler returns (the underlying ctypes memory is reused).
            buf = frame.frame_buffer.tobytes()
            width = int(frame.width)
            height = int(frame.height)
            assert isinstance(buf, bytes)
            if width <= 0 or height <= 0:
                # Spurious frame; ignore. ``read`` will keep waiting.
                return
            bgra = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 4)
            rgb = np.ascontiguousarray(bgra[..., 2::-1])
            with self._frame_lock:
                self._latest_frame = (rgb, width, height)
                self._frame_event.set()

        def on_closed() -> None:
            pass

        capture.event(on_frame_arrived)
        capture.event(on_closed)

        try:
            self._control = capture.start_free_threaded()
        except OSError as exc:
            raise RuntimeError(f"Failed to start WGC session: {exc}") from exc

    @override
    def read(self) -> np.ndarray:
        """Block on the latest-frame slot and return one RGB ndarray."""
        if not self._frame_event.wait(timeout=self._frame_timeout):
            # ``close`` may have set the event; re-check the closed flag
            # before raising ``TimeoutError`` so the message stays accurate.
            if self._closed:
                raise RuntimeError("Capture is closed")
            raise TimeoutError(
                f"No frame arrived within {self._frame_timeout}s",
            )
        with self._frame_lock:
            if self._closed:
                # ``close`` raced ahead and woke us; do not return a frame.
                raise RuntimeError("Capture is closed")
            slot = self._latest_frame
            self._latest_frame = None
            self._frame_event.clear()
        if slot is None:
            # Event was set but slot was already drained; treat as timeout.
            raise TimeoutError(
                f"No frame arrived within {self._frame_timeout}s",
            )
        rgb, _w, _h = slot
        return rgb

    @override
    def close(self) -> None:
        """Stop the WGC session, wake any waiter, and drain the slot."""
        if self._closed:
            return
        self._closed = True
        try:
            # ``self._control`` is typed as ``object`` (no stubs for the
            # CaptureControl class); reach for ``.stop()`` via Any.
            cast(Any, self._control).stop()
        except Exception as exc:  # noqa: BLE001 - close() must not raise
            warnings.warn(
                f"WGC stop() failed: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
        # Wake any thread blocked in ``read`` so it observes ``_closed = True``.
        self._frame_event.set()
        with self._frame_lock:
            self._latest_frame = None
