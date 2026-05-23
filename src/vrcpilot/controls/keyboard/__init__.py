"""Synthetic keyboard input for VRChat (platform dispatch).

Keys are passed as :class:`Key` (a :class:`enum.StrEnum`); combos are
expressed by passing multiple keys to :func:`press` rather than parsing
strings like ``"ctrl+c"``. The platform backend is imported lazily on
first call so the off-platform implementation never loads.
"""

from __future__ import annotations

import sys

from vrcpilot.controls.guard import ensure_target as ensure_target
from vrcpilot.controls.keyboard.base import Key, Keyboard

__all__ = ["Key", "Keyboard", "down", "press", "up"]

_instance: Keyboard | None = None


def _get() -> Keyboard:
    """Return the platform backend, constructing it on first call.

    Deferred so import does not eagerly open ``/dev/uinput`` (Linux) or
    pull pydirectinput stubs on the wrong platform.
    """
    global _instance
    if _instance is None:
        if sys.platform == "win32":
            from vrcpilot.controls.keyboard.windows import Win32Keyboard

            _instance = Win32Keyboard()
        elif sys.platform == "linux":
            from vrcpilot.controls.keyboard.linux import LinuxKeyboard

            _instance = LinuxKeyboard()
        else:
            raise NotImplementedError(
                f"controls.keyboard is not supported on {sys.platform}"
            )
    return _instance


def press(
    *keys: Key,
    duration: float = 0.1,
    focus: bool = True,
    pid: int | None = None,
) -> None:
    """See :meth:`Keyboard.press`."""
    _get().press(*keys, duration=duration, focus=focus, pid=pid)


def down(*keys: Key, focus: bool = True, pid: int | None = None) -> None:
    """See :meth:`Keyboard.down`."""
    _get().down(*keys, focus=focus, pid=pid)


def up(*keys: Key, focus: bool = True, pid: int | None = None) -> None:
    """See :meth:`Keyboard.up`."""
    _get().up(*keys, focus=focus, pid=pid)
