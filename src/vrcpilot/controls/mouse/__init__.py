"""Synthetic mouse input for VRChat (platform dispatch).

The concrete backend (``LinuxMouse`` / ``Win32Mouse``) lives in
:mod:`vrcpilot.controls.mouse.linux` /
:mod:`vrcpilot.controls.mouse.windows` and is imported lazily on first
call to :func:`_get` so the off-platform implementation never loads.
"""

from __future__ import annotations

import sys

from vrcpilot.controls.guard import ensure_target
from vrcpilot.controls.mouse.base import Mouse, MouseButton

__all__ = [
    "Mouse",
    "MouseButton",
    "click",
    "ensure_target",
    "move",
    "press",
    "release",
    "scroll",
]

_instance: Mouse | None = None


def _get() -> Mouse:
    """Return the platform backend, constructing it on first call.

    Deferred so import does not eagerly open ``/dev/uinput`` (Linux) or
    pull pydirectinput stubs on the wrong platform.
    """
    global _instance
    if _instance is None:
        if sys.platform == "win32":
            from vrcpilot.controls.mouse.windows import Win32Mouse

            _instance = Win32Mouse()
        elif sys.platform == "linux":
            from vrcpilot.controls.mouse.linux import LinuxMouse

            _instance = LinuxMouse()
        else:
            raise NotImplementedError(
                f"controls.mouse is not supported on {sys.platform}"
            )
    return _instance


def move(x: int, y: int, *, relative: bool = False, focus: bool = True) -> None:
    """See :meth:`Mouse.move`."""
    _get().move(x, y, relative=relative, focus=focus)


def click(
    *buttons: MouseButton,
    count: int = 1,
    duration: float = 0.0,
    focus: bool = True,
) -> None:
    """See :meth:`Mouse.click`."""
    _get().click(*buttons, count=count, duration=duration, focus=focus)


def press(*buttons: MouseButton, focus: bool = True) -> None:
    """See :meth:`Mouse.press`."""
    _get().press(*buttons, focus=focus)


def release(*buttons: MouseButton, focus: bool = True) -> None:
    """See :meth:`Mouse.release`."""
    _get().release(*buttons, focus=focus)


def scroll(amount: int, *, focus: bool = True) -> None:
    """See :meth:`Mouse.scroll`."""
    _get().scroll(amount, focus=focus)
