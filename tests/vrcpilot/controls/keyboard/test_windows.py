"""Tests for :mod:`vrcpilot.controls.keyboard.windows`.

The module is Windows-only -- it imports ``pydirectinput`` which
issues real ``SendInput`` calls into the active session as soon as
``keyDown`` / ``keyUp`` are called. The module raises
:class:`ImportError` on non-Windows hosts, so a module-level skip
guards the rest of the file.

The tests here are minimal: ``Win32Keyboard._do_down`` / ``_do_up`` is
a one-line wrapper around ``pydirectinput.keyDown(key.value)`` /
``pydirectinput.keyUp(key.value)``. Verifying the wrapping behaviour
without mocking ``pydirectinput`` would inject real keystrokes into
whichever session the CI runner is logged into. The full pipeline is
exercised by ``tests/e2e/keyboard.py`` against a real VRChat window;
this file just confirms construction is healthy and the public
``_do_*`` methods accept :class:`Key` arguments.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip(
        "vrcpilot.controls.keyboard.windows is Windows-only",
        allow_module_level=True,
    )

from vrcpilot.controls.keyboard.base import Key  # noqa: E402
from vrcpilot.controls.keyboard.windows import Win32Keyboard  # noqa: E402


class TestWin32KeyboardConstructs:
    """Construction must not raise and the resulting object dispatches.

    Real ``Win32Keyboard()`` does not open any device (pydirectinput
    is stateless at import time), so this test is essentially a smoke
    check that the module imports cleanly on the Windows runner. The
    dispatch call below taps SHIFT_LEFT once -- a benign key that
    will not produce visible character output if the runner is
    inactive.
    """

    def test_construct_and_dispatch_one_key(self) -> None:
        kb = Win32Keyboard()
        # Press + release SHIFT_LEFT, a modifier that produces no
        # observable side effect when no key follows it. Validates
        # that the ``pydirectinput.keyDown`` / ``keyUp`` calls accept
        # the string forwarded from ``Key.value``.
        kb._do_down(Key.SHIFT_LEFT)
        kb._do_up(Key.SHIFT_LEFT)
