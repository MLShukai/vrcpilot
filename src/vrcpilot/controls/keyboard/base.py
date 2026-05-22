"""Cross-platform :class:`Key` enum and :class:`Keyboard` ABC.

Lives in its own module so platform backends can import it without
dragging each other in.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import StrEnum

from vrcpilot.controls.guard import ensure_target


class Key(StrEnum):
    """Normalized key identifiers.

    Values follow pydirectinput naming so the Win32 backend can
    forward ``key.value`` straight through.
    """

    # Letters
    A = "a"
    B = "b"
    C = "c"
    D = "d"
    E = "e"
    F = "f"
    G = "g"
    H = "h"
    I = "i"  # noqa: E741
    J = "j"
    K = "k"
    L = "l"
    M = "m"
    N = "n"
    O = "o"  # noqa: E741
    P = "p"
    Q = "q"
    R = "r"
    S = "s"
    T = "t"
    U = "u"
    V = "v"
    W = "w"
    X = "x"
    Y = "y"
    Z = "z"

    # Digits (identifier cannot start with a digit, so prefix NUM_)
    NUM_0 = "0"
    NUM_1 = "1"
    NUM_2 = "2"
    NUM_3 = "3"
    NUM_4 = "4"
    NUM_5 = "5"
    NUM_6 = "6"
    NUM_7 = "7"
    NUM_8 = "8"
    NUM_9 = "9"

    # Function keys (F1..F12 — F13..F24 omitted from the public surface
    # for now; add when a concrete need arises)
    F1 = "f1"
    F2 = "f2"
    F3 = "f3"
    F4 = "f4"
    F5 = "f5"
    F6 = "f6"
    F7 = "f7"
    F8 = "f8"
    F9 = "f9"
    F10 = "f10"
    F11 = "f11"
    F12 = "f12"

    # Modifiers (generic + L/R)
    SHIFT = "shift"
    SHIFT_LEFT = "shiftleft"
    SHIFT_RIGHT = "shiftright"
    CTRL = "ctrl"
    CTRL_LEFT = "ctrlleft"
    CTRL_RIGHT = "ctrlright"
    ALT = "alt"
    ALT_LEFT = "altleft"
    ALT_RIGHT = "altright"
    WIN = "win"
    WIN_LEFT = "winleft"
    WIN_RIGHT = "winright"

    # Navigation / arrows
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    HOME = "home"
    END = "end"
    PAGE_UP = "pageup"
    PAGE_DOWN = "pagedown"

    # Editing
    BACKSPACE = "backspace"
    DELETE = "delete"
    INSERT = "insert"
    TAB = "tab"
    ENTER = "enter"
    ESCAPE = "escape"
    SPACE = "space"

    # Symbols
    MINUS = "-"
    EQUALS = "="
    LBRACKET = "["
    RBRACKET = "]"
    BACKSLASH = "\\"
    SEMICOLON = ";"
    QUOTE = "'"
    COMMA = ","
    PERIOD = "."
    SLASH = "/"
    BACKTICK = "`"


class Keyboard(ABC):
    """Keyboard ABC: runs :func:`ensure_target`, then delegates to ``_do_*``.

    Public methods accept one or more :class:`Key` values; combos go
    down left-to-right and come up in reverse so modifiers outlive the
    keys they modify (the ``Ctrl+C`` convention). Every public method
    raises :class:`TypeError` when called with zero keys.
    """

    def press(self, *keys: Key, duration: float = 0.1, focus: bool = True) -> None:
        """Tap ``keys`` simultaneously, holding for ``duration`` seconds.

        The 0.1s default is tuned for Unity / VRChat — shorter holds
        (including ``0.0``) get dropped in practice.
        """
        if not keys:
            raise TypeError("press() requires at least one Key")
        if focus:
            ensure_target()
        for k in keys:
            self._do_down(k)
        time.sleep(duration)
        for k in reversed(keys):
            self._do_up(k)

    def down(self, *keys: Key, focus: bool = True) -> None:
        """Press and hold ``keys`` until a matching :meth:`up`.

        Half-action; only valid within a single Python process. For a
        one-shot combo prefer ``press(Key.CTRL, Key.C)`` over the
        explicit down / press / up triple.
        """
        if not keys:
            raise TypeError("down() requires at least one Key")
        if focus:
            ensure_target()
        for k in keys:
            self._do_down(k)

    def up(self, *keys: Key, focus: bool = True) -> None:
        """Release ``keys`` previously pressed with :meth:`down`.

        Passing the same argument list to :meth:`down` and :meth:`up`
        yields LIFO release order.
        """
        if not keys:
            raise TypeError("up() requires at least one Key")
        if focus:
            ensure_target()
        for k in reversed(keys):
            self._do_up(k)

    @abstractmethod
    def _do_down(self, key: Key) -> None: ...

    @abstractmethod
    def _do_up(self, key: Key) -> None: ...
