"""Win32 helpers shared between window control and screen capture."""

from __future__ import annotations

import ctypes
import sys

if sys.platform != "win32":
    raise ImportError

import pywintypes
import win32gui
import win32process

# Configure ``SetThreadDpiAwarenessContext`` once at import time so we do
# not repeat the assignment on every ``get_window_rect`` call. Explicit
# argtypes / restype are required so that the 64-bit
# ``DPI_AWARENESS_CONTEXT`` handle is not truncated to 32 bits when
# ctypes marshals the Python int via the default ``c_int`` rule.
ctypes.windll.user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
ctypes.windll.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p


# DPI awareness context handle for ``SetThreadDpiAwarenessContext``.
#
# ``-4`` is the documented pseudo-handle for ``PER_MONITOR_AWARE_V2``.
# See: https://learn.microsoft.com/en-us/windows/win32/api/windef/ne-windef-dpi_awareness_context
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


def find_vrchat_hwnd(pid: int) -> int | None:
    """Return the visible top-level HWND owned by *pid*, or ``None``."""
    result: list[int] = []

    def _callback(hwnd: int, _lparam: int) -> bool:
        # Always continue enumeration. Returning False to stop early
        # makes pywin32 raise a spurious ``EnumWindows`` access-denied
        # error (Win32 interprets False as a callback failure and
        # surfaces GetLastError); enumerating fully is cheap enough.
        _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
        if found_pid == pid and win32gui.IsWindowVisible(hwnd):
            result.append(hwnd)
        return True

    win32gui.EnumWindows(_callback, 0)
    return result[0] if result else None


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Return ``(x, y, width, height)`` of *hwnd* in physical screen pixels.

    Switches the calling thread to per-monitor DPI aware V2 for the
    duration of the call so ``GetWindowRect`` returns physical pixels
    matching what :mod:`mss` grabs; thread-local rather than process-
    wide so no other code is affected. Returns ``None`` when the HWND
    has been destroyed or the rectangle is degenerate.
    """
    set_thread_dpi = ctypes.windll.user32.SetThreadDpiAwarenessContext
    old_ctx = set_thread_dpi(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    try:
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except pywintypes.error:
            return None
    finally:
        set_thread_dpi(old_ctx)

    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None
    return (int(left), int(top), int(width), int(height))
