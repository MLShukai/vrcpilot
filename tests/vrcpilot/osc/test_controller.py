"""Behaviour spec for :class:`vrcpilot.osc.InputController`.

These are *integration-real* tests: a real :class:`OscSender` (via the
``sender`` fixture in :mod:`conftest`) speaks to a real loopback
OSC server, and every assertion is made against the bytes that
arrived. Specifically, ``time.sleep`` is **not** mocked — tap timing
is verified by wall-clock elapsed time on a small ``button_hold``
budget.

The shape of every behaviour is "I called ``ctrl.<method>(...)``,
this exact ``(address, args, ...)`` sequence reached the wire".
"""

from __future__ import annotations

import time

import pytest

from vrcpilot.osc.controller import CHATBOX_MAX_LENGTH, InputController
from vrcpilot.osc.sender import OscSender

from .conftest import LoopbackOsc


@pytest.fixture
def controller(sender: OscSender) -> InputController:
    """A controller with ``button_hold=0`` so tap tests run instantly.

    Tests that need to observe tap timing construct their own
    :class:`InputController` with an explicit ``button_hold``.
    """
    return InputController(sender, button_hold=0.0)


# Map from controller method to the OSC address it must emit.
# Kept as a module-level table so the parametrize ids are stable and
# adding a new axis / tap / hold is a one-line change.
AXIS_CASES: list[tuple[str, str]] = [
    ("vertical", "/input/Vertical"),
    ("horizontal", "/input/Horizontal"),
    ("look_horizontal", "/input/LookHorizontal"),
    ("use_axis_right", "/input/UseAxisRight"),
    ("grab_axis_right", "/input/GrabAxisRight"),
    ("move_hold_fb", "/input/MoveHoldFB"),
    ("spin_hold_cw_ccw", "/input/SpinHoldCwCcw"),
    ("spin_hold_ud", "/input/SpinHoldUD"),
    ("spin_hold_lr", "/input/SpinHoldLR"),
]

TAP_CASES: list[tuple[str, str]] = [
    ("jump", "/input/Jump"),
    ("voice", "/input/Voice"),
    ("panic", "/input/PanicButton"),
    ("quick_menu_toggle_left", "/input/QuickMenuToggleLeft"),
    ("quick_menu_toggle_right", "/input/QuickMenuToggleRight"),
    ("drop_left", "/input/DropLeft"),
    ("drop_right", "/input/DropRight"),
    ("comfort_left", "/input/ComfortLeft"),
    ("comfort_right", "/input/ComfortRight"),
]

HOLD_CASES: list[tuple[str, str]] = [
    ("run", "/input/Run"),
    ("hold_voice", "/input/Voice"),
    ("move_forward", "/input/MoveForward"),
    ("move_backward", "/input/MoveBackward"),
    ("move_left", "/input/MoveLeft"),
    ("move_right", "/input/MoveRight"),
    ("look_left", "/input/LookLeft"),
    ("look_right", "/input/LookRight"),
    ("use_left", "/input/UseLeft"),
    ("use_right", "/input/UseRight"),
    ("grab_left", "/input/GrabLeft"),
    ("grab_right", "/input/GrabRight"),
]


class TestConstruction:
    """``button_hold`` is validated at construction, not on first use."""

    def test_default_button_hold_constructs_without_error(self, sender: OscSender):
        # The default is documented as ``0.05`` in the constructor;
        # the spec here is "calling without an argument succeeds", not
        # the literal default value.
        InputController(sender)

    @pytest.mark.parametrize("button_hold", [0.0, 0.001, 0.05, 1.5])
    def test_non_negative_button_hold_is_accepted(
        self, sender: OscSender, button_hold: float
    ):
        InputController(sender, button_hold=button_hold)

    @pytest.mark.parametrize("button_hold", [-0.001, -0.05, -1.0])
    def test_negative_button_hold_is_rejected_at_construction(
        self, sender: OscSender, button_hold: float
    ):
        with pytest.raises(ValueError, match="button_hold must be >= 0"):
            InputController(sender, button_hold=button_hold)


class TestAxes:
    """Each axis method routes a float to the documented ``/input/*``
    address."""

    @pytest.mark.parametrize(("method_name", "address"), AXIS_CASES)
    @pytest.mark.parametrize("value", [-1.0, -0.5, 0.0, 0.5, 1.0])
    def test_axis_method_emits_float_message_at_documented_address(
        self,
        controller: InputController,
        loopback_osc: LoopbackOsc,
        method_name: str,
        address: str,
        value: float,
    ):
        getattr(controller, method_name)(value)
        loopback_osc.recorder.wait_for(1)

        rx_address, rx_args = loopback_osc.recorder.messages[0]
        assert rx_address == address
        assert rx_args == (value,)
        # OSC ``f`` tag, not ``i`` — the receiver sees a Python float.
        assert isinstance(rx_args[0], float)

    @pytest.mark.parametrize(("method_name", "address"), AXIS_CASES)
    def test_axis_rejects_out_of_range_via_sender_validation(
        self,
        controller: InputController,
        loopback_osc: LoopbackOsc,
        method_name: str,
        address: str,
    ):
        """Axes share the sender's ``[-1.0, 1.0]`` float validation.

        Spec: bad input must raise *and* must not silently send a
        capped or rounded value to VRChat.
        """
        del address  # part of the parametrize id only
        with pytest.raises(ValueError, match="float value must be in"):
            getattr(controller, method_name)(1.5)

        with pytest.raises(AssertionError):
            loopback_osc.recorder.wait_for(1, timeout=0.05)


class TestTapButtons:
    @pytest.mark.parametrize(("method_name", "address"), TAP_CASES)
    def test_tap_emits_press_then_release_at_documented_address(
        self,
        controller: InputController,
        loopback_osc: LoopbackOsc,
        method_name: str,
        address: str,
    ):
        getattr(controller, method_name)()
        loopback_osc.recorder.wait_for(2)

        assert loopback_osc.recorder.messages == [
            (address, (1,)),
            (address, (0,)),
        ]

    def test_tap_sleeps_button_hold_seconds_between_press_and_release(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        """Real wall-clock proof that ``button_hold`` actually sleeps.

        Without the sleep, a paired ``on``/``off`` arrives faster than
        VRChat's input poll can latch the press. We use a
        deliberately-tight 0.05s budget so the test stays fast but
        still detects a missing sleep (which would complete in
        microseconds).
        """
        ctrl = InputController(sender, button_hold=0.05)

        before = time.monotonic()
        ctrl.jump()
        elapsed = time.monotonic() - before

        loopback_osc.recorder.wait_for(2)
        # Allow some slack below 0.05 for OS scheduler jitter and the
        # fact that ``time.sleep`` may return slightly early on some
        # platforms; the load-bearing assertion is "elapsed is on the
        # order of button_hold", not "elapsed >= button_hold exactly".
        assert elapsed >= 0.04, (
            f"tap should sleep ~button_hold (0.05s) between on/off; "
            f"observed {elapsed:.4f}s — likely the sleep was skipped"
        )
        assert loopback_osc.recorder.messages == [
            ("/input/Jump", (1,)),
            ("/input/Jump", (0,)),
        ]

    def test_tap_with_button_hold_zero_skips_the_sleep_entirely(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        """``button_hold=0.0`` is documented as "no sleep".

        Real wall-clock verification: the round-trip must finish in
        well under 50ms even on a busy CI runner. We do not assert a
        tighter bound because UDP loopback latency is platform-dependent.
        """
        ctrl = InputController(sender, button_hold=0.0)

        before = time.monotonic()
        ctrl.jump()
        elapsed = time.monotonic() - before

        loopback_osc.recorder.wait_for(2)
        assert elapsed < 0.05, (
            f"button_hold=0.0 must not sleep; observed {elapsed:.4f}s "
            f"which suggests a sleep happened anyway"
        )
        assert loopback_osc.recorder.messages == [
            ("/input/Jump", (1,)),
            ("/input/Jump", (0,)),
        ]


class TestHoldButtons:
    @pytest.mark.parametrize(("method_name", "address"), HOLD_CASES)
    @pytest.mark.parametrize("active", [True, False])
    def test_hold_method_emits_active_flag_at_documented_address(
        self,
        controller: InputController,
        loopback_osc: LoopbackOsc,
        method_name: str,
        address: str,
        active: bool,
    ):
        getattr(controller, method_name)(active)
        loopback_osc.recorder.wait_for(1)

        assert loopback_osc.recorder.messages == [(address, (1 if active else 0,))]

    @pytest.mark.parametrize(("method_name", "address"), HOLD_CASES)
    def test_hold_method_default_arg_presses_the_button(
        self,
        controller: InputController,
        loopback_osc: LoopbackOsc,
        method_name: str,
        address: str,
    ):
        """Calling the hold method with no argument should *press*, not
        release.

        Catches a refactor that flips the default to ``False`` — a
        movement key that defaults to "release" would silently make
        scripts a no-op.
        """
        getattr(controller, method_name)()
        loopback_osc.recorder.wait_for(1)
        assert loopback_osc.recorder.messages == [(address, (1,))]

    def test_voice_tap_and_hold_voice_target_the_same_address(
        self, controller: InputController, loopback_osc: LoopbackOsc
    ):
        """VRChat's ``/input/Voice`` is reused for tap (toggle) and hold (PTT).

        The InputController exposes them as separate methods
        (``voice()`` / ``hold_voice(...)``) but they MUST route to the
        same OSC address — otherwise the toggle and push-to-mute
        semantics would target different VRChat input slots.
        """
        controller.voice()  # tap = press + release
        controller.hold_voice(True)  # explicit press
        controller.hold_voice(False)  # explicit release
        loopback_osc.recorder.wait_for(4)

        assert loopback_osc.recorder.messages == [
            ("/input/Voice", (1,)),  # tap on
            ("/input/Voice", (0,)),  # tap off
            ("/input/Voice", (1,)),  # hold on
            ("/input/Voice", (0,)),  # hold off
        ]


class TestChatbox:
    """``chatbox`` posts text via ``/chatbox/input`` with two bool flags."""

    def test_defaults_send_immediately_with_sfx_on(
        self, controller: InputController, loopback_osc: LoopbackOsc
    ):
        controller.chatbox("hello")
        loopback_osc.recorder.wait_for(1)

        assert loopback_osc.recorder.messages == [
            ("/chatbox/input", ("hello", True, True))
        ]

    @pytest.mark.parametrize("send", [True, False])
    @pytest.mark.parametrize("sfx", [True, False])
    def test_send_and_sfx_flags_appear_at_positions_2_and_3(
        self,
        controller: InputController,
        loopback_osc: LoopbackOsc,
        send: bool,
        sfx: bool,
    ):
        controller.chatbox("hi", send=send, sfx=sfx)
        loopback_osc.recorder.wait_for(1)

        assert loopback_osc.recorder.messages == [("/chatbox/input", ("hi", send, sfx))]

    def test_truthy_and_falsy_send_sfx_are_normalized_to_bool(
        self, controller: InputController, loopback_osc: LoopbackOsc
    ):
        """``bool(...)`` normalization on the flag args.

        Spec: VRChat expects a pair of OSC bool tags; passing an int
        (e.g. ``send=1``) should not change the wire tag.
        """
        # The pyright suppression below is needed because the public
        # signature is ``bool``; the test exercises the runtime coercion
        # guard that callers actually rely on.
        controller.chatbox("hi", send=1, sfx=0)  # type: ignore[arg-type]
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == "/chatbox/input"
        assert args == ("hi", True, False)
        # Wire tag check: positions 2/3 must be ``bool``, not int.
        assert isinstance(args[1], bool) and isinstance(args[2], bool)

    def test_text_at_exactly_max_length_is_accepted(
        self, controller: InputController, loopback_osc: LoopbackOsc
    ):
        text = "a" * CHATBOX_MAX_LENGTH
        controller.chatbox(text)
        loopback_osc.recorder.wait_for(1)

        assert loopback_osc.recorder.messages == [
            ("/chatbox/input", (text, True, True))
        ]

    def test_text_one_char_over_max_length_is_rejected(
        self, controller: InputController, loopback_osc: LoopbackOsc
    ):
        text = "a" * (CHATBOX_MAX_LENGTH + 1)
        with pytest.raises(
            ValueError,
            match=rf"chatbox text exceeds {CHATBOX_MAX_LENGTH} chars",
        ):
            controller.chatbox(text)

        # Length validation must happen before the UDP write.
        with pytest.raises(AssertionError):
            loopback_osc.recorder.wait_for(1, timeout=0.05)

    def test_empty_string_is_accepted(
        self, controller: InputController, loopback_osc: LoopbackOsc
    ):
        """Empty text clears the chatbox per VRChat docs — must be allowed."""
        controller.chatbox("")
        loopback_osc.recorder.wait_for(1)

        assert loopback_osc.recorder.messages == [("/chatbox/input", ("", True, True))]


class TestTyping:
    """``typing`` toggles the chatbox typing indicator via a single bool."""

    @pytest.mark.parametrize("active", [True, False])
    def test_typing_emits_int_at_chatbox_typing_address(
        self,
        controller: InputController,
        loopback_osc: LoopbackOsc,
        active: bool,
    ):
        controller.typing(active)
        loopback_osc.recorder.wait_for(1)

        # ``typing`` goes through ``send_bool`` -> arrives as int 0/1
        # on the wire (VRChat rejects the OSC ``T``/``F`` tags).
        assert loopback_osc.recorder.messages == [
            ("/chatbox/typing", (1 if active else 0,))
        ]
