"""Linux ``inputtino``-backed :class:`Keyboard` implementation.

Loads only on ``sys.platform == "linux"``; importing on any other
platform raises :class:`ImportError` so misuse surfaces immediately.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError("vrcpilot.controls.keyboard.linux is Linux-only")

from typing import override

import inputtino

from vrcpilot.controls.keyboard.base import Key, Keyboard

# Exhaustive Key -> inputtino.KeyCode map; tests assert
# set(_INPUTTINO_CODES) == set(Key) so a missing entry surfaces
# at test time rather than as a production KeyError.
_INPUTTINO_CODES: dict[Key, inputtino.KeyCode] = {
    # Letters
    Key.A: inputtino.KeyCode.A,
    Key.B: inputtino.KeyCode.B,
    Key.C: inputtino.KeyCode.C,
    Key.D: inputtino.KeyCode.D,
    Key.E: inputtino.KeyCode.E,
    Key.F: inputtino.KeyCode.F,
    Key.G: inputtino.KeyCode.G,
    Key.H: inputtino.KeyCode.H,
    Key.I: inputtino.KeyCode.I,
    Key.J: inputtino.KeyCode.J,
    Key.K: inputtino.KeyCode.K,
    Key.L: inputtino.KeyCode.L,
    Key.M: inputtino.KeyCode.M,
    Key.N: inputtino.KeyCode.N,
    Key.O: inputtino.KeyCode.O,
    Key.P: inputtino.KeyCode.P,
    Key.Q: inputtino.KeyCode.Q,
    Key.R: inputtino.KeyCode.R,
    Key.S: inputtino.KeyCode.S,
    Key.T: inputtino.KeyCode.T,
    Key.U: inputtino.KeyCode.U,
    Key.V: inputtino.KeyCode.V,
    Key.W: inputtino.KeyCode.W,
    Key.X: inputtino.KeyCode.X,
    Key.Y: inputtino.KeyCode.Y,
    Key.Z: inputtino.KeyCode.Z,
    # Digits
    Key.NUM_0: inputtino.KeyCode.KEY_0,
    Key.NUM_1: inputtino.KeyCode.KEY_1,
    Key.NUM_2: inputtino.KeyCode.KEY_2,
    Key.NUM_3: inputtino.KeyCode.KEY_3,
    Key.NUM_4: inputtino.KeyCode.KEY_4,
    Key.NUM_5: inputtino.KeyCode.KEY_5,
    Key.NUM_6: inputtino.KeyCode.KEY_6,
    Key.NUM_7: inputtino.KeyCode.KEY_7,
    Key.NUM_8: inputtino.KeyCode.KEY_8,
    Key.NUM_9: inputtino.KeyCode.KEY_9,
    # Function keys
    Key.F1: inputtino.KeyCode.F1,
    Key.F2: inputtino.KeyCode.F2,
    Key.F3: inputtino.KeyCode.F3,
    Key.F4: inputtino.KeyCode.F4,
    Key.F5: inputtino.KeyCode.F5,
    Key.F6: inputtino.KeyCode.F6,
    Key.F7: inputtino.KeyCode.F7,
    Key.F8: inputtino.KeyCode.F8,
    Key.F9: inputtino.KeyCode.F9,
    Key.F10: inputtino.KeyCode.F10,
    Key.F11: inputtino.KeyCode.F11,
    Key.F12: inputtino.KeyCode.F12,
    # Modifiers
    Key.SHIFT: inputtino.KeyCode.SHIFT,
    Key.SHIFT_LEFT: inputtino.KeyCode.LEFT_SHIFT,
    Key.SHIFT_RIGHT: inputtino.KeyCode.RIGHT_SHIFT,
    Key.CTRL: inputtino.KeyCode.CTRL,
    Key.CTRL_LEFT: inputtino.KeyCode.LEFT_CONTROL,
    Key.CTRL_RIGHT: inputtino.KeyCode.RIGHT_CONTROL,
    Key.ALT: inputtino.KeyCode.ALT,
    Key.ALT_LEFT: inputtino.KeyCode.LEFT_ALT,
    Key.ALT_RIGHT: inputtino.KeyCode.RIGHT_ALT,
    # Generic WIN has no inputtino equivalent — map to LEFT_WIN
    # (the spec already treats generic modifiers as left-mapped).
    Key.WIN: inputtino.KeyCode.LEFT_WIN,
    Key.WIN_LEFT: inputtino.KeyCode.LEFT_WIN,
    Key.WIN_RIGHT: inputtino.KeyCode.RIGHT_WIN,
    # Navigation / arrows
    Key.UP: inputtino.KeyCode.UP,
    Key.DOWN: inputtino.KeyCode.DOWN,
    Key.LEFT: inputtino.KeyCode.LEFT,
    Key.RIGHT: inputtino.KeyCode.RIGHT,
    Key.HOME: inputtino.KeyCode.HOME,
    Key.END: inputtino.KeyCode.END,
    Key.PAGE_UP: inputtino.KeyCode.PAGE_UP,
    Key.PAGE_DOWN: inputtino.KeyCode.PAGE_DOWN,
    # Editing
    Key.BACKSPACE: inputtino.KeyCode.BACKSPACE,
    Key.DELETE: inputtino.KeyCode.DELETE,
    Key.INSERT: inputtino.KeyCode.INSERT,
    Key.TAB: inputtino.KeyCode.TAB,
    Key.ENTER: inputtino.KeyCode.ENTER,
    Key.ESCAPE: inputtino.KeyCode.ESC,
    Key.SPACE: inputtino.KeyCode.SPACE,
    # Symbols
    Key.MINUS: inputtino.KeyCode.MINUS,
    Key.EQUALS: inputtino.KeyCode.PLUS,
    Key.LBRACKET: inputtino.KeyCode.OPEN_BRACKET,
    Key.RBRACKET: inputtino.KeyCode.CLOSE_BRACKET,
    Key.BACKSLASH: inputtino.KeyCode.BACKSLASH,
    Key.SEMICOLON: inputtino.KeyCode.SEMICOLON,
    Key.QUOTE: inputtino.KeyCode.QUOTE,
    Key.COMMA: inputtino.KeyCode.COMMA,
    Key.PERIOD: inputtino.KeyCode.PERIOD,
    Key.SLASH: inputtino.KeyCode.SLASH,
    Key.BACKTICK: inputtino.KeyCode.TILDE,
}


class LinuxKeyboard(Keyboard):
    """``inputtino``-backed :class:`Keyboard` (opens ``/dev/uinput``)."""

    def __init__(self) -> None:
        self._imp = inputtino.Keyboard()

    @override
    def _do_down(self, key: Key) -> None:
        self._imp.press(_INPUTTINO_CODES[key])

    @override
    def _do_up(self, key: Key) -> None:
        self._imp.release(_INPUTTINO_CODES[key])
