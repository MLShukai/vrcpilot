"""Windows ``pydirectinput``-backed :class:`Mouse` implementation.

Loads only on ``sys.platform == "win32"``; importing on any other
platform raises :class:`ImportError` so misuse surfaces immediately.
"""

from __future__ import annotations

import sys

if sys.platform != "win32":
    raise ImportError("vrcpilot.controls.mouse.windows is Windows-only")

import ctypes
from typing import Any, override

# pydirectinput ships no stubs; alias to Any once so call sites stay
# clean instead of needing reportUnknownMemberType ignores per call.
import pydirectinput as _pydirectinput_module  # pyright: ignore[reportMissingTypeStubs]

from vrcpilot.controls.mouse.base import Mouse, MouseButton

pydirectinput: Any = _pydirectinput_module

# Disable pydirectinput's "cursor at (0, 0) panic" — VRChat workflows
# legitimately move the cursor to corners and we do not want a hard
# exit from a synthetic input call.
pydirectinput.FAILSAFE = False

# MOUSEEVENTF_WHEEL is the SendInput flag for vertical wheel events.
# pydirectinput 1.0.4 does not ship a scroll() helper, so we
# synthesize the event using its already-imported ctypes structures.
_MOUSEEVENTF_WHEEL = 0x0800
_WHEEL_DELTA = 120


def _scroll_wheel(amount: int) -> None:
    """Synthesize a vertical wheel event via ``SendInput``.

    Win32 convention is positive = up; the caller must already have
    sign-flipped to match the public API (positive = down).
    """
    extra = ctypes.c_ulong(0)
    ii = pydirectinput.Input_I()
    ii.mi = pydirectinput.MouseInput(
        0,
        0,
        ctypes.c_ulong(amount * _WHEEL_DELTA).value,
        _MOUSEEVENTF_WHEEL,
        0,
        ctypes.pointer(extra),
    )
    inp = pydirectinput.Input(ctypes.c_ulong(0), ii)
    pydirectinput.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


class Win32Mouse(Mouse):
    """``pydirectinput``-backed :class:`Mouse` (no mss capture)."""

    @override
    def _do_move(self, x: int, y: int, *, relative: bool) -> None:
        if relative:
            pydirectinput.moveRel(x, y)
        else:
            pydirectinput.moveTo(x, y)

    @override
    def _do_press(self, button: MouseButton) -> None:
        pydirectinput.mouseDown(button=button)

    @override
    def _do_release(self, button: MouseButton) -> None:
        pydirectinput.mouseUp(button=button)

    @override
    def _do_scroll(self, amount: int) -> None:
        # Public API: positive = down. Win32: positive = up. Flip.
        _scroll_wheel(-amount)
