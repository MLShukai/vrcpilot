"""VRChat window z-order control (focus / unfocus / is_foreground).

Windows and Linux (X11 / XWayland). Native Wayland is unsupported -
``focus()`` / ``unfocus()`` / ``is_foreground()`` warn and return
``False``.
"""

from __future__ import annotations

import sys


def focus() -> bool:
    """Bring the running VRChat window to the foreground.

    Restored if minimized (Win32 ``ShowWindow(SW_RESTORE)``; on X11 an
    EWMH window manager typically deminimizes in response to
    ``_NET_ACTIVE_WINDOW``). Only meaningful in Desktop mode — VR
    exclusive mode has no desktop window to surface.

    Raises:
        NotImplementedError: Platform other than Windows or Linux.

    Returns:
        ``True`` on success. ``False`` when VRChat is not running, the
        window cannot be located, the platform call fails, or the
        session is native Wayland (also emits :class:`RuntimeWarning`).
    """
    if sys.platform == "win32":
        from .windows import focus_window as _impl

        return _impl()
    if sys.platform == "linux":
        from .linux import focus_window as _impl

        return _impl()
    raise NotImplementedError(f"focus() is not supported on {sys.platform}")


def is_foreground() -> bool:
    """Return ``True`` when the running VRChat window is foreground.

    Raises:
        NotImplementedError: Platform other than Windows or Linux.

    Returns:
        ``True`` when VRChat owns the foreground window. ``False`` when
        VRChat is not running, the window cannot be located, the
        platform call fails, or the session is native Wayland (also
        emits :class:`RuntimeWarning`).
    """
    if sys.platform == "win32":
        from .windows import is_window_foreground as _impl

        return _impl()
    if sys.platform == "linux":
        from .linux import is_window_foreground as _impl

        return _impl()
    raise NotImplementedError(f"is_foreground() is not supported on {sys.platform}")


def unfocus() -> bool:
    """Send the running VRChat window to the bottom of the z-order.

    Unlike minimizing, no other window is activated, so input focus
    stays where the caller had it.

    Raises:
        NotImplementedError: Platform other than Windows or Linux.

    Returns:
        ``True`` on success. ``False`` when VRChat is not running, the
        window cannot be located, the platform call fails, or the
        session is native Wayland (also emits :class:`RuntimeWarning`).
    """
    if sys.platform == "win32":
        from .windows import unfocus_window as _impl

        return _impl()
    if sys.platform == "linux":
        from .linux import unfocus_window as _impl

        return _impl()
    raise NotImplementedError(f"unfocus() is not supported on {sys.platform}")
