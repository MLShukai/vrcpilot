"""Platform-agnostic VRChat window geometry lookup.

Wayland detection is intentionally **not** done here — Wayland still
allows process and window discovery, only pixel grabs are blocked, so
the check belongs at the screenshot/capture layer.

The platform-specific window walk + rect query runs in the native
extension (:mod:`vrcpilot._native`); this module keeps the PID
resolution and the ``VRChatMultipleInstancesError`` / not-running policy
in Python.
"""

from __future__ import annotations

import sys

from vrcpilot import _native, process
from vrcpilot.process import VRChatMultipleInstancesError, VRChatNotRunningError


def get_vrchat_window_rect(
    *, pid: int | None = None
) -> tuple[int, int, int, int] | None:
    """Locate the VRChat window's screen rect for capture and click
    translation.

    Args:
        pid: Disambiguates when multiple VRChat instances run. When
            ``None``, :func:`vrcpilot.process.resolve_pid` picks the
            sole instance (or raises).

    Returns:
        ``(x, y, width, height)`` in desktop pixels, or ``None`` when
        VRChat is not running, the window has not yet been mapped, or
        the platform backend cannot reach its display. Returning ``None``
        (rather than raising) lets polling callers retry without
        try/except.

    Raises:
        VRChatMultipleInstancesError: ``pid`` was omitted and more than
            one VRChat is running. Surfaced (not swallowed) so callers
            can prompt the user for ``--pid`` rather than silently
            picking one.
        NotImplementedError: Running on a platform other than Windows or
            Linux.
    """
    try:
        resolved = process.resolve_pid(pid)
    except VRChatMultipleInstancesError:
        raise
    except VRChatNotRunningError:
        return None

    if sys.platform not in ("win32", "linux"):
        raise NotImplementedError(
            f"get_vrchat_window_rect() is not supported on {sys.platform}"
        )
    return _native.window.get_window_rect(resolved)
