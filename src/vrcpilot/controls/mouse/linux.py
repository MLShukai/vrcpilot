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
import mss

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
    moves is captured once from ``mss.monitors[0]`` (whole desktop).
    """

    def __init__(self) -> None:
        self._imp = inputtino.Mouse()
        time.sleep(_UINPUT_BIND_SETTLE)
        # Match screenshot.py: explicit instantiate / close (not
        # the context manager) so test fakes can be plain mocks
        # without implementing __enter__ / __exit__.
        sct = mss.MSS()
        try:
            bbox = sct.monitors[0]
            self._screen_w = int(bbox["width"])
            self._screen_h = int(bbox["height"])
        finally:
            sct.close()

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
