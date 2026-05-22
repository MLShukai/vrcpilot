"""Windows ``pydirectinput``-backed :class:`Keyboard` implementation.

Loads only on ``sys.platform == "win32"``; importing on any other
platform raises :class:`ImportError` so misuse surfaces immediately.
"""

from __future__ import annotations

import sys

if sys.platform != "win32":
    raise ImportError("vrcpilot.controls.keyboard.windows is Windows-only")

from typing import Any, override

# pydirectinput ships no stubs; alias to Any once so call sites stay
# clean instead of needing reportUnknownMemberType ignores per call.
import pydirectinput as _pydirectinput_module  # pyright: ignore[reportMissingTypeStubs]

from vrcpilot.controls.keyboard.base import Key, Keyboard

pydirectinput: Any = _pydirectinput_module

# Disable pydirectinput's "cursor at (0, 0) panic" — VRChat workflows
# legitimately move the cursor to corners and we do not want a hard
# exit from a synthetic input call. Idempotent with mouse setting
# the same flag (they share the same module reference).
pydirectinput.FAILSAFE = False


class Win32Keyboard(Keyboard):
    """``pydirectinput``-backed :class:`Keyboard`.

    :class:`Key` values are forwarded as ``key.value`` directly into
    ``pydirectinput.KEYBOARD_MAPPING``; add a translation table here
    if any member turns out to be unsupported.
    """

    @override
    def _do_down(self, key: Key) -> None:
        pydirectinput.keyDown(key.value)

    @override
    def _do_up(self, key: Key) -> None:
        pydirectinput.keyUp(key.value)
