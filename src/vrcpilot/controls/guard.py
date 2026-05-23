"""Pre-input safety check: VRChat must be running and foreground."""

from __future__ import annotations

import time

from vrcpilot import window
from vrcpilot.process import resolve_pid
from vrcpilot.session import is_wayland_native

from .errors import VRChatNotFocusedError

# Some WMs (notably GNOME Mutter) silently ignore the first
# ``_NET_ACTIVE_WINDOW`` request as focus-stealing prevention but honor
# repeated requests once the requesting client looks "persistent".
# Repeat ``focus`` + probe up to ``_FOCUS_RECHECK_TIMEOUT`` seconds at
# ``_FOCUS_RECHECK_INTERVAL`` granularity before giving up.
_FOCUS_RECHECK_TIMEOUT: float = 1.0
_FOCUS_RECHECK_INTERVAL: float = 0.05


def ensure_target(*, pid: int | None = None) -> int:
    """Verify VRChat is running and the foreground window.

    Returns the resolved PID so callers (notably :meth:`Mouse._to_desktop`)
    can reuse it without re-running :func:`vrcpilot.process.resolve_pid`
    and racing against VRChat exiting between the two lookups.

    Idempotent; safe to call before every input event. Native Wayland
    raises :class:`NotImplementedError` because the focus retry loop
    would never converge there.

    Raises:
        VRChatNotRunningError: No VRChat process exists.
        VRChatMultipleInstancesError: ``pid`` is omitted and multiple
            VRChat processes are running.
        VRChatNotFocusedError: VRChat cannot be brought to the foreground.
    """
    if is_wayland_native():
        raise NotImplementedError(
            "controls.ensure_target requires X11 or XWayland; "
            "native Wayland is not supported"
        )
    resolved = resolve_pid(pid)
    if window.is_foreground(pid=resolved):
        return resolved
    deadline = time.monotonic() + _FOCUS_RECHECK_TIMEOUT
    while True:
        if not window.focus(pid=resolved):
            raise VRChatNotFocusedError(
                "VRChat is not the foreground window and focus() failed"
            )
        if window.is_foreground(pid=resolved):
            return resolved
        if time.monotonic() >= deadline:
            raise VRChatNotFocusedError(
                "VRChat is not the foreground window after focus()"
            )
        time.sleep(_FOCUS_RECHECK_INTERVAL)
