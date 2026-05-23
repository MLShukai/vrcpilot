"""Platform-agnostic VRChat window geometry lookup.

Wayland detection is intentionally **not** done here — Wayland still
allows process and window discovery, only pixel grabs are blocked, so
the check belongs at the screenshot/capture layer.
"""

from __future__ import annotations

import sys

from vrcpilot import process
from vrcpilot.process import VRChatMultipleInstancesError, VRChatNotRunningError

if sys.platform == "win32":

    def _get_vrchat_rect_win32(*, pid: int) -> tuple[int, int, int, int] | None:
        """Win32 path: ``find_vrchat_hwnd(pid)`` -> ``get_window_rect``."""
        from vrcpilot.windows import find_vrchat_hwnd, get_window_rect

        hwnd = find_vrchat_hwnd(pid)
        if hwnd is None:
            return None
        return get_window_rect(hwnd)


if sys.platform == "linux":

    def _get_vrchat_rect_linux(*, pid: int) -> tuple[int, int, int, int] | None:
        """Linux path: open the X11 display, locate the VRChat window, query
        geometry."""
        from vrcpilot.linux import find_vrchat_window, get_window_rect, open_x11_display

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


def get_vrchat_window_rect(
    *, pid: int | None = None
) -> tuple[int, int, int, int] | None:
    """Return the VRChat window ``(x, y, width, height)`` in desktop pixels.

    *pid* selects the target instance when multiple VRChat processes are
    running. When omitted, :func:`vrcpilot.process.resolve_pid` chooses the
    sole running instance.

    Returns ``None`` when VRChat is not running, the window cannot be located,
    or the geometry query fails. Raises
    :class:`vrcpilot.process.VRChatMultipleInstancesError` when *pid* is
    omitted and multiple VRChat processes are running, so callers can prompt
    for ``--pid`` rather than silently choosing one. Raises
    :class:`NotImplementedError` outside Windows / Linux.
    """
    try:
        resolved = process.resolve_pid(pid)
    except VRChatMultipleInstancesError:
        raise
    except VRChatNotRunningError:
        return None

    if sys.platform == "win32":
        return _get_vrchat_rect_win32(pid=resolved)
    if sys.platform == "linux":
        return _get_vrchat_rect_linux(pid=resolved)
    raise NotImplementedError(
        f"get_vrchat_window_rect() is not supported on {sys.platform}"
    )
