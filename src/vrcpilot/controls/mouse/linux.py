"""Linux ``inputtino``-backed :class:`Mouse` implementation.

Loads only on ``sys.platform == "linux"``; importing on any other
platform raises :class:`ImportError` so misuse surfaces immediately.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError("vrcpilot.controls.mouse.linux is Linux-only")

import time
from typing import override

import inputtino

from vrcpilot.linux import open_x11_display

from .base import Mouse, MouseButton

# inputtino's scroll API takes distance in 120-per-notch high-resolution
# units; we expose plain notches and multiply on the way down.
_SCROLL_NOTCH = 120

# Grace period after ``inputtino.Mouse()`` creates the ``/dev/uinput``
# device, before the first event is allowed through. Mirrors the same
# concern as :data:`vrcpilot.controls.keyboard.linux._UINPUT_BIND_SETTLE`:
# X11 / libinput subscribes to new uinput devices asynchronously via
# udev, so events issued inside this window are silently dropped.
_UINPUT_BIND_SETTLE: float = 0.5

_BUTTON_MAP: dict[MouseButton, inputtino.MouseButton] = {
    MouseButton.LEFT: inputtino.MouseButton.LEFT,
    MouseButton.MIDDLE: inputtino.MouseButton.MIDDLE,
    MouseButton.RIGHT: inputtino.MouseButton.RIGHT,
}


class LinuxMouse(Mouse):
    """``inputtino``-backed :class:`Mouse`.

    Opens ``/dev/uinput`` at construction. Screen size for absolute
    moves is read once from the python-xlib root screen dimensions
    (``width_in_pixels`` / ``height_in_pixels``).
    """

    def __init__(self) -> None:
        self._imp = inputtino.Mouse()
        time.sleep(_UINPUT_BIND_SETTLE)
        # open_x11_display() makes the caller responsible for closing the
        # connection, so probe the root screen size under try/finally.
        display = open_x11_display()
        if display is None:
            raise RuntimeError(
                "X11 display unavailable; LinuxMouse needs a reachable "
                "display for absolute moves"
            )
        try:
            screen = display.screen()
            self._screen_w = int(screen.width_in_pixels)
            self._screen_h = int(screen.height_in_pixels)
        finally:
            display.close()

    @override
    def _do_move(self, x: int, y: int, *, relative: bool) -> None:
        if relative:
            self._imp.move(x, y)
        else:
            self._imp.move_abs(x, y, self._screen_w, self._screen_h)

    @override
    def _do_press(self, button: MouseButton) -> None:
        self._imp.press(_BUTTON_MAP[button])

    @override
    def _do_release(self, button: MouseButton) -> None:
        self._imp.release(_BUTTON_MAP[button])

    @override
    def _do_scroll(self, amount: int) -> None:
        self._imp.scroll_vertical(amount * _SCROLL_NOTCH)
