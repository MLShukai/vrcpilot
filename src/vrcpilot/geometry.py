"""Platform-agnostic VRChat window geometry lookup.

Wayland detection is intentionally **not** done here — Wayland still
allows process and window discovery, only pixel grabs are blocked, so
the check belongs at the screenshot/capture layer.
"""

from __future__ import annotations

import sys

from vrcpilot.process import find_pid

if sys.platform == "win32":

    def _get_vrchat_rect_win32() -> tuple[int, int, int, int] | None:
        """Win32 path: ``find_pid`` -> ``find_vrchat_hwnd`` -> ``get_window_rect``."""
        from vrcpilot.windows import find_vrchat_hwnd, get_window_rect

        pid = find_pid()
        if pid is None:
            return None
        hwnd = find_vrchat_hwnd(pid)
        if hwnd is None:
            return None
        return get_window_rect(hwnd)


if sys.platform == "linux":

    def _get_vrchat_rect_x11() -> tuple[int, int, int, int] | None:
        """X11 path: open display, locate the VRChat window, query geometry."""
        from vrcpilot.linux import find_vrchat_window, get_window_rect, open_x11_display

        pid = find_pid()
        if pid is None:
            return None
        display = open_x11_display()
        if display is None:
            return None
        try:
            window = find_vrchat_window(display, pid)
            if window is None:
                return None
            return get_window_rect(display, window)
        finally:
            display.close()


def get_vrchat_window_rect() -> tuple[int, int, int, int] | None:
    """Return the VRChat window ``(x, y, width, height)`` in desktop pixels.

    ``None`` when VRChat is not running, the window cannot be located,
    or the geometry query fails. Raises :class:`NotImplementedError`
    outside Windows / Linux (rather than returning ``None``) so direct
    callers without their own platform guard fail loudly.
    """
    if sys.platform == "win32":
        return _get_vrchat_rect_win32()
    if sys.platform == "linux":
        return _get_vrchat_rect_x11()
    raise NotImplementedError(
        f"get_vrchat_window_rect() is not supported on {sys.platform}"
    )
