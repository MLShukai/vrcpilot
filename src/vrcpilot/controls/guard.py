"""Pre-input safety check: VRChat must be running and foreground."""

from __future__ import annotations

import time

from vrcpilot import window
from vrcpilot.process import VRChatNotRunningError, find_pid
from vrcpilot.session import is_wayland_native

from .errors import VRChatNotFocusedError

# Some WMs (notably GNOME Mutter) silently ignore the first
# ``_NET_ACTIVE_WINDOW`` request as focus-stealing prevention but honor
# repeated requests once the requesting client looks "persistent".
# Repeat ``focus`` + probe up to ``_FOCUS_RECHECK_TIMEOUT`` seconds at
# ``_FOCUS_RECHECK_INTERVAL`` granularity before giving up.
_FOCUS_RECHECK_TIMEOUT: float = 1.0
_FOCUS_RECHECK_INTERVAL: float = 0.05


def ensure_target() -> None:
    """Verify VRChat is running and the foreground window.

    Idempotent; safe to call before every input event. Native Wayland
    raises :class:`NotImplementedError` because the focus retry loop
    would never converge there. Raises :class:`VRChatNotRunningError`
    when no VRChat process exists, or :class:`VRChatNotFocusedError`
    when the window cannot be brought to the foreground.
    """
    if is_wayland_native():
        raise NotImplementedError(
            "controls.ensure_target requires X11 or XWayland; "
            "native Wayland is not supported"
        )
    if find_pid() is None:
        raise VRChatNotRunningError("VRChat is not running")
    if window.is_foreground():
        return
    deadline = time.monotonic() + _FOCUS_RECHECK_TIMEOUT
    while True:
        if not window.focus():
            raise VRChatNotFocusedError(
                "VRChat is not the foreground window and focus() failed"
            )
        if window.is_foreground():
            return
        if time.monotonic() >= deadline:
            raise VRChatNotFocusedError(
                "VRChat is not the foreground window after focus()"
            )
        time.sleep(_FOCUS_RECHECK_INTERVAL)
