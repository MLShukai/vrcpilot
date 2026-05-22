"""Synthetic keyboard input for VRChat (platform dispatch).

Keys are passed as :class:`Key` (a :class:`enum.StrEnum`) so pyright
and IDE completion catch typos. Combos can be expressed either as
explicit ``down`` / ``press`` / ``up`` triples or, equivalently, as a
single :func:`press` call with multiple positional keys
(``press(Key.CTRL_LEFT, Key.C)`` for ``Ctrl+C``); there is no
``"ctrl+c"`` string parsing.

The concrete backend (``LinuxKeyboard`` / ``Win32Keyboard``) lives in
:mod:`vrcpilot.controls.keyboard.linux` /
:mod:`vrcpilot.controls.keyboard.windows` and is imported lazily on
first call to :func:`_get` so the off-platform implementation never
loads.
"""

from __future__ import annotations

import sys

from vrcpilot.controls.guard import ensure_target
from vrcpilot.controls.keyboard.base import Key, Keyboard

__all__ = ["Key", "Keyboard", "down", "ensure_target", "press", "up"]

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


def press(*keys: Key, duration: float = 0.1, focus: bool = True) -> None:
    """See :meth:`Keyboard.press`."""
    _get().press(*keys, duration=duration, focus=focus)


def down(*keys: Key, focus: bool = True) -> None:
    """See :meth:`Keyboard.down`."""
    _get().down(*keys, focus=focus)


def up(*keys: Key, focus: bool = True) -> None:
    """See :meth:`Keyboard.up`."""
    _get().up(*keys, focus=focus)
