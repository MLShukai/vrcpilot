"""Tests for :mod:`vrcpilot.cli.osc` (send / axis / tap / hold / chatbox /
typing / avatar).

The CLI calls into :mod:`vrcpilot.osc` via the
:func:`vrcpilot.cli.osc._make_sender` factory. Patching that factory
to return an :class:`~vrcpilot.osc.OscSender` constructed with an
injected :class:`~tests.fakes.FakeUDPClient` keeps every internal
collaborator real (validation, dispatch, forwarding) while swapping
out the UDP boundary. ``FakeUDPClient`` is therefore the single
boundary fake for this suite.
"""

from __future__ import annotations

import io

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeUDPClient
from vrcpilot.cli import main
from vrcpilot.cli.osc import _AXIS_NAMES, _HOLD_NAMES, _TAP_NAMES, _to_method
from vrcpilot.osc import OscSender
from vrcpilot.osc.controller import InputController


@pytest.fixture
def fake_client(mocker: MockerFixture) -> FakeUDPClient:
    """Wire ``vrcpilot.cli.osc._make_sender`` to a recording sender.

    Builds a real :class:`OscSender` with a :class:`FakeUDPClient`
    injected via ``client=``, patches the factory to return that sender,
    and hands the inner :class:`FakeUDPClient` back so tests can inspect
    ``.sent``.
    """
    client = FakeUDPClient()
    sender = OscSender(client=client)
    mocker.patch("vrcpilot.cli.osc._make_sender", return_value=sender)
    return client


class TestOscSend:
    @pytest.mark.parametrize("truthy", ["true", "1"])
    def test_send_bool_true_sends_one(self, fake_client: FakeUDPClient, truthy: str):
        exit_code = main(["osc", "send", "/foo", "--bool", truthy])

        assert exit_code == 0
        assert fake_client.sent == [("/foo", 1)]

    @pytest.mark.parametrize("falsy", ["false", "0"])
    def test_send_bool_false_sends_zero(self, fake_client: FakeUDPClient, falsy: str):
        exit_code = main(["osc", "send", "/foo", "--bool", falsy])

        assert exit_code == 0
        assert fake_client.sent == [("/foo", 0)]

    def test_send_int_in_range(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "send", "/foo", "--int", "42"])

        assert exit_code == 0
        assert fake_client.sent == [("/foo", 42)]

    def test_send_int_out_of_range_returns_1(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client  # fixture wires the patch; we only need stderr here

        exit_code = main(["osc", "send", "/foo", "--int", "256"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_send_float_in_range(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "send", "/foo", "--float", "0.5"])

        assert exit_code == 0
        assert fake_client.sent == [("/foo", 0.5)]

    def test_send_float_out_of_range_returns_1(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        exit_code = main(["osc", "send", "/foo", "--float", "2.0"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_send_requires_a_type_flag(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        with pytest.raises(SystemExit) as excinfo:
            main(["osc", "send", "/foo"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""

    def test_send_rejects_multiple_type_flags(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        with pytest.raises(SystemExit) as excinfo:
            main(["osc", "send", "/foo", "--bool", "1", "--int", "1"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""

    def test_silent_on_success(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        exit_code = main(["osc", "send", "/foo", "--int", "1"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestOscConnection:
    def test_host_and_port_are_passed_to_sender_factory(self, mocker: MockerFixture):
        client = FakeUDPClient()
        sender = OscSender(client=client)
        factory = mocker.patch("vrcpilot.cli.osc._make_sender", return_value=sender)

        exit_code = main(
            [
                "osc",
                "--host",
                "1.2.3.4",
                "--port",
                "9100",
                "send",
                "/foo",
                "--int",
                "1",
            ]
        )

        assert exit_code == 0
        factory.assert_called_once_with("1.2.3.4", 9100)


class TestOscDispatch:
    def test_no_action_exits_non_zero(self, capsys: pytest.CaptureFixture[str]):
        # ``add_subparsers(required=True)`` on the osc parser makes
        # argparse error out when ``vrcpilot osc`` is invoked without
        # an action.
        with pytest.raises(SystemExit) as excinfo:
            main(["osc"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""


# Map every CLI kebab-case name to the OSC address its
# InputController method writes to. Locking these wirings at the CLI
# boundary catches both kebab-case typos and accidental method renames.
_AXIS_ADDRESSES: dict[str, str] = {
    "vertical": "/input/Vertical",
    "horizontal": "/input/Horizontal",
    "look-horizontal": "/input/LookHorizontal",
    "use-axis-right": "/input/UseAxisRight",
    "grab-axis-right": "/input/GrabAxisRight",
    "move-hold-fb": "/input/MoveHoldFB",
    "spin-hold-cw-ccw": "/input/SpinHoldCwCcw",
    "spin-hold-ud": "/input/SpinHoldUD",
    "spin-hold-lr": "/input/SpinHoldLR",
}

_TAP_ADDRESSES: dict[str, str] = {
    "jump": "/input/Jump",
    "voice": "/input/Voice",
    "panic": "/input/PanicButton",
    "quick-menu-toggle-left": "/input/QuickMenuToggleLeft",
    "quick-menu-toggle-right": "/input/QuickMenuToggleRight",
    "drop-left": "/input/DropLeft",
    "drop-right": "/input/DropRight",
    "comfort-left": "/input/ComfortLeft",
    "comfort-right": "/input/ComfortRight",
}

_HOLD_ADDRESSES: dict[str, str] = {
    "run": "/input/Run",
    "hold-voice": "/input/Voice",
    "move-forward": "/input/MoveForward",
    "move-backward": "/input/MoveBackward",
    "move-left": "/input/MoveLeft",
    "move-right": "/input/MoveRight",
    "look-left": "/input/LookLeft",
    "look-right": "/input/LookRight",
    "use-left": "/input/UseLeft",
    "use-right": "/input/UseRight",
    "grab-left": "/input/GrabLeft",
    "grab-right": "/input/GrabRight",
}


class TestOscAxis:
    @pytest.mark.parametrize(
        ("name", "expected_address"), list(_AXIS_ADDRESSES.items())
    )
    def test_each_axis_name_dispatches(
        self,
        fake_client: FakeUDPClient,
        name: str,
        expected_address: str,
    ):
        exit_code = main(["osc", "axis", name, "0.5"])

        assert exit_code == 0
        assert fake_client.sent == [(expected_address, 0.5)]

    def test_axis_value_out_of_range_returns_1(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        exit_code = main(["osc", "axis", "vertical", "2.0"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_axis_unknown_name_argparse_error(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["osc", "axis", "bogus", "0.0"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""


class TestOscTap:
    def test_tap_emits_press_then_release(
        self, fake_client: FakeUDPClient, mocker: MockerFixture
    ):
        mocker.patch("vrcpilot.osc.controller.time.sleep")

        exit_code = main(["osc", "tap", "jump"])

        assert exit_code == 0
        assert fake_client.sent == [("/input/Jump", 1), ("/input/Jump", 0)]

    def test_button_hold_passes_through_to_sleep(
        self, fake_client: FakeUDPClient, mocker: MockerFixture
    ):
        del fake_client
        sleep_spy = mocker.patch("vrcpilot.osc.controller.time.sleep")

        exit_code = main(["osc", "--button-hold", "0.07", "tap", "jump"])

        assert exit_code == 0
        assert sleep_spy.call_count == 1
        assert sleep_spy.call_args.args == (0.07,)

    @pytest.mark.parametrize(("name", "expected_address"), list(_TAP_ADDRESSES.items()))
    def test_each_tap_name_dispatches(
        self,
        fake_client: FakeUDPClient,
        mocker: MockerFixture,
        name: str,
        expected_address: str,
    ):
        mocker.patch("vrcpilot.osc.controller.time.sleep")

        exit_code = main(["osc", "tap", name])

        assert exit_code == 0
        assert fake_client.sent == [
            (expected_address, 1),
            (expected_address, 0),
        ]

    def test_tap_unknown_name_argparse_error(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["osc", "tap", "bogus"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""


class TestOscHold:
    def test_hold_on_sends_one(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "hold", "run", "on"])

        assert exit_code == 0
        assert fake_client.sent == [("/input/Run", 1)]

    def test_hold_off_sends_zero(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "hold", "run", "off"])

        assert exit_code == 0
        assert fake_client.sent == [("/input/Run", 0)]

    @pytest.mark.parametrize(
        ("name", "expected_address"), list(_HOLD_ADDRESSES.items())
    )
    def test_each_hold_name_dispatches(
        self,
        fake_client: FakeUDPClient,
        name: str,
        expected_address: str,
    ):
        exit_code = main(["osc", "hold", name, "on"])

        assert exit_code == 0
        assert fake_client.sent == [(expected_address, 1)]

    def test_hold_state_required_argparse_error(
        self, capsys: pytest.CaptureFixture[str]
    ):
        with pytest.raises(SystemExit) as excinfo:
            main(["osc", "hold", "run"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""

    def test_hold_unknown_name_argparse_error(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["osc", "hold", "bogus", "on"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""


class TestOscChoiceCoverage:
    """Forward-direction safety net: every CLI choice must resolve to a
    callable on a real :class:`InputController`.

    Catches kebab-case typos in :data:`_AXIS_NAMES` /
    :data:`_TAP_NAMES` / :data:`_HOLD_NAMES` and method renames /
    deletions on :class:`InputController`. The reverse direction
    (``InputController`` methods without a CLI choice) is intentionally
    NOT asserted -- chatbox / typing live outside axis/tap/hold.
    """

    @pytest.mark.parametrize("name", _AXIS_NAMES)
    def test_axis_name_resolves_to_callable(self, name: str):
        controller = InputController(OscSender(client=FakeUDPClient()))
        method = getattr(controller, _to_method(name))
        assert callable(method)

    @pytest.mark.parametrize("name", _TAP_NAMES)
    def test_tap_name_resolves_to_callable(self, name: str):
        controller = InputController(OscSender(client=FakeUDPClient()))
        method = getattr(controller, _to_method(name))
        assert callable(method)

    @pytest.mark.parametrize("name", _HOLD_NAMES)
    def test_hold_name_resolves_to_callable(self, name: str):
        controller = InputController(OscSender(client=FakeUDPClient()))
        method = getattr(controller, _to_method(name))
        assert callable(method)


class TestOscChatbox:
    def test_positional_text_dispatches(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "chatbox", "hello world"])

        assert exit_code == 0
        assert fake_client.sent == [("/chatbox/input", ["hello world", True, True])]

    def test_no_send_and_no_sfx_flip_flags(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "chatbox", "hi", "--no-send", "--no-sfx"])

        assert exit_code == 0
        assert fake_client.sent == [("/chatbox/input", ["hi", False, False])]

    def test_text_too_long_returns_1(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        exit_code = main(["osc", "chatbox", "x" * 145])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_stdin_text_when_no_positional(
        self, fake_client: FakeUDPClient, mocker: MockerFixture
    ):
        # Piped stdin: not a tty (StringIO.isatty() returns False), so
        # the CLI consumes stdin verbatim (no strip).
        mocker.patch(
            "vrcpilot.cli.osc.sys.stdin",
            new=io.StringIO("from stdin"),
        )

        exit_code = main(["osc", "chatbox"])

        assert exit_code == 0
        assert fake_client.sent == [("/chatbox/input", ["from stdin", True, True])]

    def test_no_text_and_tty_returns_2(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client  # the autouse conftest fixture already pins isatty=True

        exit_code = main(["osc", "chatbox"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err != ""


class TestOscTyping:
    def test_typing_on_sends_one(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "typing", "on"])

        assert exit_code == 0
        assert fake_client.sent == [("/chatbox/typing", 1)]

    def test_typing_off_sends_zero(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "typing", "off"])

        assert exit_code == 0
        assert fake_client.sent == [("/chatbox/typing", 0)]

    def test_typing_state_required_argparse_error(
        self, capsys: pytest.CaptureFixture[str]
    ):
        with pytest.raises(SystemExit) as excinfo:
            main(["osc", "typing"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""


class TestOscAvatar:
    @pytest.mark.parametrize(
        ("flag_value", "expected"),
        [("true", 1), ("1", 1), ("false", 0), ("0", 0)],
    )
    def test_avatar_send_bool(
        self,
        fake_client: FakeUDPClient,
        flag_value: str,
        expected: int,
    ):
        exit_code = main(["osc", "avatar", "MyParam", "--bool", flag_value])

        assert exit_code == 0
        assert fake_client.sent == [("/avatar/parameters/MyParam", expected)]

    def test_avatar_send_int(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "avatar", "MyParam", "--int", "42"])

        assert exit_code == 0
        assert fake_client.sent == [("/avatar/parameters/MyParam", 42)]

    def test_avatar_send_int_out_of_range_returns_1(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        exit_code = main(["osc", "avatar", "MyParam", "--int", "256"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_avatar_send_float(self, fake_client: FakeUDPClient):
        exit_code = main(["osc", "avatar", "MyParam", "--float", "0.5"])

        assert exit_code == 0
        assert fake_client.sent == [("/avatar/parameters/MyParam", 0.5)]

    def test_avatar_send_float_out_of_range_returns_1(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        exit_code = main(["osc", "avatar", "MyParam", "--float", "2.0"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_avatar_invalid_name_returns_1(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        exit_code = main(["osc", "avatar", "Bad/Name", "--bool", "1"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_avatar_requires_a_type_flag(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        with pytest.raises(SystemExit) as excinfo:
            main(["osc", "avatar", "MyParam"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""

    def test_avatar_rejects_multiple_type_flags(
        self,
        fake_client: FakeUDPClient,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_client

        with pytest.raises(SystemExit) as excinfo:
            main(["osc", "avatar", "MyParam", "--bool", "1", "--int", "1"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""
