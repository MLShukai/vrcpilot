"""Tests for :mod:`vrcpilot.controls.keyboard.linux`.

The module is Linux-only and the real backend opens ``/dev/uinput``.
Three module-level skips gate the rest of the file:

1. Non-Linux platforms cannot import the module at all
   (:mod:`vrcpilot.controls.keyboard.linux` raises :class:`ImportError`
   on ``sys.platform != "linux"``).
2. Linux hosts without ``/dev/uinput`` write access cannot construct
   :class:`LinuxKeyboard` (inputtino opens the device at constructor
   time). Skip there with a pointer to the e2e setup instructions.
3. ``inputtino`` itself must import cleanly.

The tests exercise the real :class:`inputtino.Keyboard` -- only
``/dev/uinput`` is involved, no virtual screen is needed. The
``_INPUTTINO_CODES`` exhaustiveness test prevents a missing :class:`Key`
member from surfacing as a runtime :class:`KeyError` deep in a press
call; it is the unit-test equivalent of the production code's promise
that every public ``Key`` has a backend mapping.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "linux":
    pytest.skip(
        "vrcpilot.controls.keyboard.linux is Linux-only",
        allow_module_level=True,
    )

from tests.helpers import has_uinput  # noqa: E402

if not has_uinput():
    pytest.skip(
        "/dev/uinput is not writable; see tests/e2e/keyboard.py for setup",
        allow_module_level=True,
    )

import inputtino  # noqa: E402

from vrcpilot.controls.keyboard.base import Key  # noqa: E402
from vrcpilot.controls.keyboard.linux import (  # noqa: E402
    _INPUTTINO_CODES,
    LinuxKeyboard,
)


class TestInputtinoCodesExhaustive:
    """Every :class:`Key` member must have an ``_INPUTTINO_CODES`` entry.

    A missing entry would surface as a :class:`KeyError` at the first
    runtime call. This test pulls the failure forward to discovery
    time so a new :class:`Key` member never escapes into production
    without a backend mapping.
    """

    def test_every_key_member_maps_to_an_inputtino_keycode(self) -> None:
        assert set(_INPUTTINO_CODES.keys()) == set(Key)

    def test_every_mapped_value_is_an_inputtino_keycode_instance(self) -> None:
        for member, code in _INPUTTINO_CODES.items():
            assert isinstance(
                code, inputtino.KeyCode
            ), f"{member!r} maps to non-KeyCode value {code!r}"

    @pytest.mark.parametrize(
        "key_name,code_name",
        [
            # Cases where the vrcpilot name differs from the inputtino
            # name and a wrong wire-up would silently produce the wrong
            # key event. Pinning these here documents the spec.
            ("ESCAPE", "ESC"),
            ("EQUALS", "PLUS"),
            ("BACKTICK", "TILDE"),
            ("LBRACKET", "OPEN_BRACKET"),
            ("RBRACKET", "CLOSE_BRACKET"),
            ("SHIFT_LEFT", "LEFT_SHIFT"),
            ("SHIFT_RIGHT", "RIGHT_SHIFT"),
            ("CTRL_LEFT", "LEFT_CONTROL"),
            ("CTRL_RIGHT", "RIGHT_CONTROL"),
            ("ALT_LEFT", "LEFT_ALT"),
            ("ALT_RIGHT", "RIGHT_ALT"),
            ("WIN_LEFT", "LEFT_WIN"),
            ("WIN_RIGHT", "RIGHT_WIN"),
            ("NUM_0", "KEY_0"),
            ("NUM_9", "KEY_9"),
        ],
    )
    def test_known_name_translations(self, key_name: str, code_name: str) -> None:
        key = getattr(Key, key_name)
        expected = getattr(inputtino.KeyCode, code_name)
        assert _INPUTTINO_CODES[key] is expected

    def test_generic_win_maps_to_left_win(self) -> None:
        # Inputtino has no "generic WIN" keycode, so the spec maps
        # ``Key.WIN`` to ``LEFT_WIN`` (matching how generic SHIFT /
        # CTRL / ALT are conventionally treated by Linux input).
        assert _INPUTTINO_CODES[Key.WIN] is inputtino.KeyCode.LEFT_WIN


class TestLinuxKeyboardConstructs:
    """:class:`LinuxKeyboard` opens ``/dev/uinput`` and is then usable.

    Real construction + real ``_do_down`` / ``_do_up`` -- the events
    flow into the kernel's uinput device. We cannot observe them
    coming back out (that would require a uinput reader fixture and
    a separate evdev pipeline) so the assertion is only that the
    calls return cleanly. The fact that nothing raises proves the
    kernel accepted the events for that keycode -- a wrong keycode
    type or out-of-range value would raise on the Python <-> C
    boundary.
    """

    def test_construct_does_not_raise(self) -> None:
        # If this fails the rest of the module is meaningless; the
        # module-level skip already filters out the common
        # "no uinput" environments, so a failure here is a real
        # regression worth investigating.
        kb = LinuxKeyboard()
        del kb  # nothing else to assert at construction time

    def test_do_down_and_do_up_accept_a_sampled_key_each(self) -> None:
        # One representative key per category: a letter, a digit, a
        # modifier, a navigation key, a symbol. Picking the full key
        # set would just multiply the kernel round-trip cost without
        # adding spec coverage.
        kb = LinuxKeyboard()

        for key in (
            Key.A,
            Key.NUM_5,
            Key.SHIFT_LEFT,
            Key.UP,
            Key.MINUS,
        ):
            kb._do_down(key)
            kb._do_up(key)


class TestLinuxKeyboardFullPressIntegration:
    """A full ``press(combo)`` via the real backend must complete cleanly.

    Drives the public :meth:`Keyboard.press` (with ``focus=False`` so
    no VRChat is needed) and lets the ABC decompose into the real
    inputtino-backed ``_do_down`` / ``_do_up``. Verifies that the
    full pipeline -- ABC sequencing + native event dispatch + the
    default 0.1 s sleep -- runs without raising. Equivalent to the
    e2e ``modifier combo`` step but without VRChat in the loop.
    """

    def test_press_combo_completes_without_raising(self) -> None:
        kb = LinuxKeyboard()

        kb.press(
            Key.CTRL_LEFT,
            Key.A,
            duration=0.0,  # skip the real sleep to keep the test fast
            focus=False,
        )
