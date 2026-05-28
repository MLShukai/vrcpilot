"""Win32 implementation of focus/unfocus for the VRChat window.

The Win32 window operations themselves run in the native extension
(:mod:`vrcpilot._native`); this module is the platform leaf the public
dispatch in :mod:`vrcpilot.window` forwards to.
"""

from __future__ import annotations

import sys

if sys.platform != "win32":
    raise ImportError

from vrcpilot import _native


def focus_window(*, pid: int) -> bool:
    """Win32 implementation of :func:`vrcpilot.window.focus`."""
    return _native.window.focus_window(pid)


def is_window_foreground(*, pid: int) -> bool:
    """Win32 implementation of :func:`vrcpilot.window.is_foreground`."""
    return _native.window.is_window_foreground(pid)


def unfocus_window(*, pid: int) -> bool:
    """Win32 implementation of :func:`vrcpilot.window.unfocus`."""
    return _native.window.unfocus_window(pid)
