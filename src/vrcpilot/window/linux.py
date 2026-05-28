"""X11/XWayland implementation of focus/unfocus for the VRChat window.

The EWMH window operations themselves run in the native extension
(:mod:`vrcpilot._native`, via x11rb). This module keeps the
Wayland-native short-circuit in Python so the :class:`RuntimeWarning`
contract stays observable and testable without a display.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError

import warnings

from vrcpilot import _native
from vrcpilot.session import is_wayland_native


def focus_window(*, pid: int) -> bool:
    """X11/XWayland implementation of :func:`vrcpilot.window.focus`."""
    if is_wayland_native():
        warnings.warn(
            "Wayland native session detected; "
            "focus()/unfocus() require X11 or XWayland.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    return _native.window.focus_window(pid)


def is_window_foreground(*, pid: int) -> bool:
    """X11/XWayland implementation of :func:`vrcpilot.window.is_foreground`."""
    if is_wayland_native():
        warnings.warn(
            "Wayland native session detected; "
            "is_foreground() requires X11 or XWayland.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    return _native.window.is_window_foreground(pid)


def unfocus_window(*, pid: int) -> bool:
    """X11/XWayland implementation of :func:`vrcpilot.window.unfocus`."""
    if is_wayland_native():
        warnings.warn(
            "Wayland native session detected; "
            "focus()/unfocus() require X11 or XWayland.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    return _native.window.unfocus_window(pid)
