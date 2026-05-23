"""VRChat window z-order control (focus / unfocus / is_foreground).

Supported on Windows and Linux (X11 / XWayland). Native Wayland sessions
emit :class:`RuntimeWarning` and return ``False`` from every entry point,
since EWMH activation primitives are not exposed there.

All three entry points share the same dispatch shape (platform select →
``resolve_pid`` → backend call → ``VRChatNotRunningError`` to ``False``),
so the common path is factored into :func:`_resolve_and_call`.
"""

from __future__ import annotations

import sys

from vrcpilot.process import (
    VRChatMultipleInstancesError,
    VRChatNotRunningError,
    resolve_pid,
)


def _resolve_and_call(impl_attr: str, *, pid: int | None) -> bool:
    """Dispatch ``impl_attr`` to the platform window backend.

    Resolves *pid* via :func:`vrcpilot.process.resolve_pid` and forwards the
    concrete PID to the backend function named *impl_attr* on the active
    platform module. ``VRChatMultipleInstancesError`` is **re-raised** so
    callers can prompt for ``--pid``; a plain :class:`VRChatNotRunningError`
    is converted to ``False`` so absence of VRChat never propagates as an
    exception out of the public entry points.

    The except-order is load-bearing: ``VRChatMultipleInstancesError`` is a
    subclass of ``VRChatNotRunningError``, so it must be caught first or it
    would be silently absorbed by the second handler.

    Raises :class:`NotImplementedError` on platforms other than Windows or
    Linux. The backend module is imported lazily on each call so that
    ``import vrcpilot.window`` does not pull in win32 / Xlib bindings on the
    wrong platform.
    """
    if sys.platform == "win32":
        from . import windows as backend
    elif sys.platform == "linux":
        from . import linux as backend
    else:
        raise NotImplementedError(f"vrcpilot.window is not supported on {sys.platform}")

    try:
        resolved = resolve_pid(pid)
    except VRChatMultipleInstancesError:
        raise
    except VRChatNotRunningError:
        return False
    impl = getattr(backend, impl_attr)
    result: bool = impl(pid=resolved)
    return result


def focus(*, pid: int | None = None) -> bool:
    """Bring the running VRChat window to the foreground, restoring it if
    minimized.

    *pid* selects the target instance when multiple VRChat processes are
    running. When omitted, :func:`vrcpilot.process.resolve_pid` chooses the
    sole running instance.

    Only meaningful in Desktop mode — VR exclusive mode has no desktop
    window to surface. Returns ``False`` (rather than raising) when VRChat
    is not running, the window cannot be located, the platform call fails,
    or the session is native Wayland (which also emits
    :class:`RuntimeWarning`). Raises
    :class:`vrcpilot.process.VRChatMultipleInstancesError` when *pid* is
    omitted and multiple VRChat processes are running. Raises
    :class:`NotImplementedError` on platforms other than Windows or Linux.
    """
    return _resolve_and_call("focus_window", pid=pid)


def is_foreground(*, pid: int | None = None) -> bool:
    """Return whether VRChat currently owns the foreground window.

    See :func:`focus` for *pid* semantics and the Windows / Linux contract.
    """
    return _resolve_and_call("is_window_foreground", pid=pid)


def unfocus(*, pid: int | None = None) -> bool:
    """Send the running VRChat window to the bottom of the z-order, leaving
    input focus where the caller had it.

    Useful for hiding VRChat without minimizing — no other window is
    activated. See :func:`focus` for *pid* semantics and the Windows /
    Linux contract.
    """
    return _resolve_and_call("unfocus_window", pid=pid)
