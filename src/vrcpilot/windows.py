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
    """Locate the visible top-level HWND owned by ``pid`` via ``EnumWindows``.

    Returns:
        An HWND when one such window exists, otherwise ``None``. Hidden
        windows (``IsWindowVisible`` False) are skipped because VRChat's
        splash/tray windows would otherwise outrank the main window.
    """
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
    """Report ``hwnd``'s outer rect in physical pixels for capture grabbing.

    Switches the calling thread to per-monitor-DPI-aware V2 so
    ``GetWindowRect`` agrees with :mod:`mss` on physical pixels; the
    switch is thread-local and restored on exit, so callers and other
    threads observe their original DPI context.

    Returns:
        ``(x, y, width, height)``, or ``None`` when the HWND has been
        destroyed or the rectangle is degenerate (non-positive size).
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
