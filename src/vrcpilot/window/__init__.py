"""VRChat window z-order control (focus / unfocus / is_foreground).

Supported on Windows and Linux (X11 / XWayland). Native Wayland sessions
emit :class:`RuntimeWarning` and return ``False`` from every entry point,
since EWMH activation primitives are not exposed there.
"""

from __future__ import annotations

import sys


def focus() -> bool:
    """Bring the running VRChat window to the foreground, restoring it if
    minimized.

    Only meaningful in Desktop mode — VR exclusive mode has no desktop
    window to surface. Returns ``False`` (rather than raising) when
    VRChat is not running, the window cannot be located, the platform
    call fails, or the session is native Wayland (which also emits
    :class:`RuntimeWarning`). Raises ``NotImplementedError`` on
    platforms other than Windows or Linux.
    """
    if sys.platform == "win32":
        from .windows import focus_window as _impl

        return _impl()
    if sys.platform == "linux":
        from .linux import focus_window as _impl

        return _impl()
    raise NotImplementedError(f"focus() is not supported on {sys.platform}")


def is_foreground() -> bool:
    """Return whether VRChat currently owns the foreground window.

    Returns ``False`` (rather than raising) when VRChat is not running,
    the window cannot be located, the platform call fails, or the
    session is native Wayland (which also emits
    :class:`RuntimeWarning`). Raises ``NotImplementedError`` on
    platforms other than Windows or Linux.
    """
    if sys.platform == "win32":
        from .windows import is_window_foreground as _impl

        return _impl()
    if sys.platform == "linux":
        from .linux import is_window_foreground as _impl

        return _impl()
    raise NotImplementedError(f"is_foreground() is not supported on {sys.platform}")


def unfocus() -> bool:
    """Send the running VRChat window to the bottom of the z-order, leaving
    input focus where the caller had it.

    Useful for hiding VRChat without minimizing — no other window is
    activated. Returns ``False`` (rather than raising) when VRChat is
    not running, the window cannot be located, the platform call fails,
    or the session is native Wayland (which also emits
    :class:`RuntimeWarning`). Raises ``NotImplementedError`` on
    platforms other than Windows or Linux.
    """
    if sys.platform == "win32":
        from .windows import unfocus_window as _impl

        return _impl()
    if sys.platform == "linux":
        from .linux import unfocus_window as _impl

        return _impl()
    raise NotImplementedError(f"unfocus() is not supported on {sys.platform}")
