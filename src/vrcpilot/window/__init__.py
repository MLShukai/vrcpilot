"""VRChat window z-order control (focus / unfocus / is_foreground).

Supported on Windows and Linux (X11 / XWayland). Native Wayland sessions
emit :class:`RuntimeWarning` and return ``False`` from every entry point,
since EWMH activation primitives are not exposed there.
"""

from __future__ import annotations

import sys

from vrcpilot.process import (
    VRChatMultipleInstancesError,
    VRChatNotRunningError,
    resolve_pid,
)


def focus(*, pid: int | None = None) -> bool:
    """Bring the running VRChat window to the foreground, restoring it if
    minimized.

    *pid* selects the target instance when multiple VRChat processes are
    running. When omitted, :func:`vrcpilot.process.resolve_pid` chooses the
    sole running instance.

    Only meaningful in Desktop mode — VR exclusive mode has no desktop
    window to surface. Returns ``False`` (rather than raising) when
    VRChat is not running, the window cannot be located, the platform
    call fails, or the session is native Wayland (which also emits
    :class:`RuntimeWarning`). Raises
    :class:`vrcpilot.process.VRChatMultipleInstancesError` when *pid*
    is omitted and multiple VRChat processes are running, so the caller
    can surface a disambiguation hint instead of silently picking one.
    Raises ``NotImplementedError`` on platforms other than Windows or
    Linux.
    """
    if sys.platform == "win32":
        from .windows import focus_window as _impl
    elif sys.platform == "linux":
        from .linux import focus_window as _impl
    else:
        raise NotImplementedError(f"focus() is not supported on {sys.platform}")

    try:
        resolved = resolve_pid(pid)
    except VRChatMultipleInstancesError:
        raise
    except VRChatNotRunningError:
        return False
    return _impl(pid=resolved)


def is_foreground(*, pid: int | None = None) -> bool:
    """Return whether VRChat currently owns the foreground window.

    *pid* selects the target instance when multiple VRChat processes are
    running. When omitted, :func:`vrcpilot.process.resolve_pid` chooses the
    sole running instance.

    Returns ``False`` (rather than raising) when VRChat is not running,
    the window cannot be located, the platform call fails, or the
    session is native Wayland (which also emits
    :class:`RuntimeWarning`). Raises
    :class:`vrcpilot.process.VRChatMultipleInstancesError` when *pid*
    is omitted and multiple VRChat processes are running. Raises
    ``NotImplementedError`` on platforms other than Windows or Linux.
    """
    if sys.platform == "win32":
        from .windows import is_window_foreground as _impl
    elif sys.platform == "linux":
        from .linux import is_window_foreground as _impl
    else:
        raise NotImplementedError(f"is_foreground() is not supported on {sys.platform}")

    try:
        resolved = resolve_pid(pid)
    except VRChatMultipleInstancesError:
        raise
    except VRChatNotRunningError:
        return False
    return _impl(pid=resolved)


def unfocus(*, pid: int | None = None) -> bool:
    """Send the running VRChat window to the bottom of the z-order, leaving
    input focus where the caller had it.

    *pid* selects the target instance when multiple VRChat processes are
    running. When omitted, :func:`vrcpilot.process.resolve_pid` chooses the
    sole running instance.

    Useful for hiding VRChat without minimizing — no other window is
    activated. Returns ``False`` (rather than raising) when VRChat is
    not running, the window cannot be located, the platform call fails,
    or the session is native Wayland (which also emits
    :class:`RuntimeWarning`). Raises
    :class:`vrcpilot.process.VRChatMultipleInstancesError` when *pid*
    is omitted and multiple VRChat processes are running. Raises
    ``NotImplementedError`` on platforms other than Windows or Linux.
    """
    if sys.platform == "win32":
        from .windows import unfocus_window as _impl
    elif sys.platform == "linux":
        from .linux import unfocus_window as _impl
    else:
        raise NotImplementedError(f"unfocus() is not supported on {sys.platform}")

    try:
        resolved = resolve_pid(pid)
    except VRChatMultipleInstancesError:
        raise
    except VRChatNotRunningError:
        return False
    return _impl(pid=resolved)
