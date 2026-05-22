"""Linux ``inputtino``-backed :class:`Mouse` implementation.

Loads only on ``sys.platform == "linux"``; importing on any other
platform raises :class:`ImportError` so misuse surfaces immediately.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError("vrcpilot.controls.mouse.linux is Linux-only")

from typing import override

import inputtino
import mss

from vrcpilot.controls.mouse.base import Mouse, MouseButton

# inputtino's scroll API takes distance in 120-per-notch high-resolution
# units; we expose plain notches and multiply on the way down.
_SCROLL_NOTCH = 120

_BUTTON_MAP: dict[MouseButton, inputtino.MouseButton] = {
    MouseButton.LEFT: inputtino.MouseButton.LEFT,
    MouseButton.MIDDLE: inputtino.MouseButton.MIDDLE,
    MouseButton.RIGHT: inputtino.MouseButton.RIGHT,
}


class LinuxMouse(Mouse):
    """``inputtino``-backed :class:`Mouse`.

    Opens ``/dev/uinput`` at construction; inputtino raises
    :class:`RuntimeError` if the caller lacks permission. Screen
    size for absolute moves is captured once from ``mss.monitors[0]``
    (whole-desktop bounding box).
    """

    def __init__(self) -> None:
        self._imp = inputtino.Mouse()
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
