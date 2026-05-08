"""Tests for :mod:`vrcpilot.osc.controller`."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from vrcpilot.osc.controller import CHATBOX_MAX_LENGTH, InputController
from vrcpilot.osc.sender import OscSender


@pytest.fixture
def sender_mock(mocker: MockerFixture):
    """A spec'd ``OscSender`` mock so we can assert on its send_* calls."""
    return mocker.Mock(spec=OscSender)


@pytest.fixture
def no_sleep(mocker: MockerFixture):
    """Patch ``time.sleep`` for tests that don't care about hold timing.

    Returned for tests that want to spy on it; using the fixture without
    capturing its value still neutralizes the real sleep so tap-tests
    run instantly.
    """
    return mocker.patch("vrcpilot.osc.controller.time.sleep")


@pytest.fixture
def controller(sender_mock, no_sleep) -> InputController:
    del no_sleep  # auto-patch sleep so taps are instant
    return InputController(sender_mock, button_hold=0.05)


class TestConstruction:
    def test_default_button_hold_does_not_raise(self, sender_mock):
        InputController(sender_mock)

    @pytest.mark.parametrize("button_hold", [0.0, 0.001, 0.05, 1.5])
    def test_accepts_non_negative_button_hold(self, sender_mock, button_hold: float):
        InputController(sender_mock, button_hold=button_hold)

    @pytest.mark.parametrize("button_hold", [-0.001, -0.05, -1.0])
    def test_rejects_negative_button_hold(self, sender_mock, button_hold: float):
        with pytest.raises(ValueError, match="button_hold must be >= 0"):
            InputController(sender_mock, button_hold=button_hold)


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


class TestAxes:
    @pytest.mark.parametrize(("method_name", "address"), AXIS_CASES)
    @pytest.mark.parametrize("value", [-1.0, -0.5, 0.0, 0.5, 1.0])
    def test_axis_method_forwards_value_to_send_float(
        self,
        sender_mock,
        controller: InputController,
        method_name: str,
        address: str,
        value: float,
    ):
        getattr(controller, method_name)(value)
        sender_mock.send_float.assert_called_once_with(address, value)
        sender_mock.send_bool.assert_not_called()


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


class TestTapButtons:
    @pytest.mark.parametrize(("method_name", "address"), TAP_CASES)
    def test_tap_method_sends_one_then_zero(
        self,
        sender_mock,
        controller: InputController,
        method_name: str,
        address: str,
    ):
        getattr(controller, method_name)()
        assert sender_mock.send_bool.call_args_list == [
            ((address, True), {}),
            ((address, False), {}),
        ]

    def test_tap_sleeps_between_press_and_release(
        self, sender_mock, no_sleep, mocker: MockerFixture
    ):
        """Tap order must be: send_bool(True) -> sleep(button_hold) -> send_bool(False)."""
        ctrl = InputController(sender_mock, button_hold=0.05)
        # Funnel both side-effecting mocks into one parent so we get a
        # global call order across them.
        recorder = mocker.Mock()
        recorder.attach_mock(sender_mock.send_bool, "send_bool")
        recorder.attach_mock(no_sleep, "sleep")

        ctrl.jump()

        assert recorder.mock_calls == [
            mocker.call.send_bool("/input/Jump", True),
            mocker.call.sleep(0.05),
            mocker.call.send_bool("/input/Jump", False),
        ]

    def test_tap_skips_sleep_when_button_hold_is_zero(self, sender_mock, no_sleep):
        ctrl = InputController(sender_mock, button_hold=0.0)
        ctrl.jump()

        no_sleep.assert_not_called()
        assert sender_mock.send_bool.call_args_list == [
            (("/input/Jump", True), {}),
            (("/input/Jump", False), {}),
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


class TestHoldButtons:
    @pytest.mark.parametrize(("method_name", "address"), HOLD_CASES)
    @pytest.mark.parametrize("active", [True, False])
    def test_hold_method_forwards_active_flag(
        self,
        sender_mock,
        controller: InputController,
        method_name: str,
        address: str,
        active: bool,
    ):
        getattr(controller, method_name)(active)
        sender_mock.send_bool.assert_called_once_with(address, active)
        sender_mock.send_float.assert_not_called()

    @pytest.mark.parametrize(("method_name", "address"), HOLD_CASES)
    def test_hold_default_active_is_true(
        self,
        sender_mock,
        controller: InputController,
        method_name: str,
        address: str,
    ):
        """Calling without an arg should send the press (True), not release."""
        getattr(controller, method_name)()
        sender_mock.send_bool.assert_called_once_with(address, True)

    def test_voice_tap_and_hold_voice_share_address(
        self, sender_mock, controller: InputController
    ):
        """``voice()`` (tap) and ``hold_voice(...)`` (hold) target
        /input/Voice."""
        controller.voice()
        controller.hold_voice(True)
        controller.hold_voice(False)
        assert sender_mock.send_bool.call_args_list == [
            (("/input/Voice", True), {}),  # voice press
            (("/input/Voice", False), {}),  # voice release
            (("/input/Voice", True), {}),  # hold_voice True
            (("/input/Voice", False), {}),  # hold_voice False
        ]


class TestChatbox:
    def test_sends_passthrough_with_defaults(
        self, sender_mock, controller: InputController
    ):
        controller.chatbox("hello")
        sender_mock.send.assert_called_once_with(
            "/chatbox/input", ["hello", True, True]
        )

    @pytest.mark.parametrize("send", [True, False])
    @pytest.mark.parametrize("sfx", [True, False])
    def test_forwards_send_and_sfx_flags(
        self, sender_mock, controller: InputController, send: bool, sfx: bool
    ):
        controller.chatbox("hi", send=send, sfx=sfx)
        sender_mock.send.assert_called_once_with("/chatbox/input", ["hi", send, sfx])

    def test_normalizes_send_and_sfx_to_bool(
        self, sender_mock, controller: InputController
    ):
        """Truthy/falsy values are coerced to ``bool`` before transmission."""
        controller.chatbox("hi", send=1, sfx=0)  # type: ignore[arg-type]
        sender_mock.send.assert_called_once_with("/chatbox/input", ["hi", True, False])

    def test_accepts_max_length(self, sender_mock, controller: InputController):
        text = "a" * CHATBOX_MAX_LENGTH
        controller.chatbox(text)
        sender_mock.send.assert_called_once_with("/chatbox/input", [text, True, True])

    def test_rejects_over_max_length(self, sender_mock, controller: InputController):
        text = "a" * (CHATBOX_MAX_LENGTH + 1)
        with pytest.raises(
            ValueError,
            match=rf"chatbox text exceeds {CHATBOX_MAX_LENGTH} chars: "
            rf"{CHATBOX_MAX_LENGTH + 1}",
        ):
            controller.chatbox(text)
        sender_mock.send.assert_not_called()

    def test_accepts_empty_string(self, sender_mock, controller: InputController):
        controller.chatbox("")
        sender_mock.send.assert_called_once_with("/chatbox/input", ["", True, True])

    @pytest.mark.parametrize("active", [True, False])
    def test_typing_forwards_active_via_send_bool(
        self, sender_mock, controller: InputController, active: bool
    ):
        controller.typing(active)
        sender_mock.send_bool.assert_called_once_with("/chatbox/typing", active)
