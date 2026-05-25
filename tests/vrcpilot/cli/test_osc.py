"""Tests for :mod:`vrcpilot.cli.osc` (send / axis / tap / hold / chatbox /
typing / avatar).

The seven OSC actions all funnel through :class:`vrcpilot.osc.OscSender`
which writes UDP datagrams. The integration-real strategy for this
suite is a loopback UDP server bound to ``127.0.0.1:<ephemeral>`` --
every CLI invocation goes through the real ``OscSender`` ->
``python-osc`` -> kernel socket -> our server, so OSC encoding,
validation, and dispatch all execute end-to-end without any mocks.

``--button-hold 0.0`` is used in tap-style tests so the real
``time.sleep`` between press and release returns immediately rather
than spending wall-clock time per case.
"""

from __future__ import annotations

import io
import socket
import threading
import time
from collections.abc import Iterator

import pytest
from pytest_mock import MockerFixture
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from vrcpilot.cli import main
from vrcpilot.cli.osc import AXIS_NAMES, HOLD_NAMES, TAP_NAMES
from vrcpilot.osc import OscSender
from vrcpilot.osc.controller import InputController

# --- Warmup tuning constants -------------------------------------------------
# Windows loopback UDP exhibits a "first-packet drop" on freshly bound
# ephemeral ports: the kernel / Windows Filtering Platform initialises
# packet-inspection state on the first inbound datagram and silently
# drops it ~100% of the time on some hosts. Subsequent packets flow
# normally as long as the destination socket stays warm.
#
# To keep every CLI test deterministic the recorder fires its own OSC
# datagrams at itself until ``_WARMUP_HITS_REQUIRED`` consecutive
# packets round-trip, then clears the buffer so the test body sees a
# clean slate. One observed packet is not enough on its own: under load
# Windows can intermittently drop the *second* packet too when source
# / destination flow state is still cold, so we require two observed
# datagrams before declaring the path open.
#
# - _WARMUP_ADDRESS: distinct from any production OSC address; the
#   buffer is cleared before yielding so warmup never leaks into
#   ``self.sent``, but the distinct name aids debugging if it ever did.
# - _WARMUP_HITS_REQUIRED: how many warmup packets must be observed
#   before considering the recorder ready. Two observed packets is
#   empirically enough; raising further only slows fixture setup.
# - _WARMUP_ATTEMPTS: hard cap on how many packets we will send. Sized
#   for the "first 1-2 drop, then they flow" pattern with generous
#   slack for slow / loaded hosts. The total budget is
#   ``_WARMUP_ATTEMPTS * _WARMUP_POLL_TIMEOUT`` (~3 s) of wall clock.
# - _WARMUP_POLL_TIMEOUT: per-attempt wait. Loopback delivery is
#   sub-ms when it works at all, so 300 ms is generous.
# - _WARMUP_POLL_INTERVAL: how often we re-check ``self.sent`` inside
#   one attempt. 10 ms matches ``wait_for_message_count``.
_WARMUP_ADDRESS = "/__warmup__"
_WARMUP_HITS_REQUIRED = 2
_WARMUP_ATTEMPTS = 10
_WARMUP_POLL_TIMEOUT = 0.3
_WARMUP_POLL_INTERVAL = 0.01


class OscRecorder:
    """Loopback UDP server collecting ``(address, args)`` tuples.

    Used as the test boundary for ``vrcpilot osc``: the CLI sends real
    UDP datagrams to ``127.0.0.1:<port>``, the recorder appends each
    message to :attr:`sent`, and the test asserts on what reached the
    wire. ``args`` is a tuple of positional args (single int / float /
    list-of-args for chatbox), matching ``python-osc``'s callback shape.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, tuple[object, ...]]] = []
        self._dispatcher = Dispatcher()
        self._dispatcher.set_default_handler(self._record)
        self._server = BlockingOSCUDPServer(("127.0.0.1", 0), self._dispatcher)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._warmup()

    @property
    def port(self) -> int:
        """The ephemeral UDP port the server bound to."""
        return self._server.server_address[1]

    def _record(self, address: str, *args: object) -> None:
        self.sent.append((address, tuple(args)))

    def _warmup(self) -> None:
        """Force-open the loopback UDP path before yielding to the test.

        See the module-level constants for the rationale: Windows can
        drop the first one or two datagrams on a freshly bound
        ephemeral port. We send OSC packets at ourselves until
        :data:`_WARMUP_HITS_REQUIRED` datagrams round-trip, then clear
        :attr:`sent` so the test body sees an empty buffer.

        Raises:
            RuntimeError: All warmup attempts elapsed without enough
                datagrams being observed. The recorder is unusable at
                that point, so failing loudly is preferable to silently
                producing flaky tests.
        """
        client = SimpleUDPClient("127.0.0.1", self.port)
        try:
            for _ in range(_WARMUP_ATTEMPTS):
                client.send_message(_WARMUP_ADDRESS, 1)
                deadline = time.monotonic() + _WARMUP_POLL_TIMEOUT
                while time.monotonic() < deadline:
                    if len(self.sent) >= _WARMUP_HITS_REQUIRED:
                        self.sent.clear()
                        return
                    time.sleep(_WARMUP_POLL_INTERVAL)
            raise RuntimeError(
                "OscRecorder warmup failed: only observed "
                f"{len(self.sent)}/{_WARMUP_HITS_REQUIRED} loopback "
                f"datagrams after {_WARMUP_ATTEMPTS} attempts of "
                f"{_WARMUP_POLL_TIMEOUT}s each on port {self.port}"
            )
        finally:
            client.close()

    def wait_for_message_count(self, count: int, timeout: float = 2.0) -> None:
        """Block until :attr:`sent` reaches ``count`` messages or timeout.

        UDP delivery on loopback is normally instantaneous but not
        guaranteed; this gives the kernel queue a deterministic window
        without waiting unconditionally.
        """
        deadline = time.monotonic() + timeout
        while len(self.sent) < count:
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"expected {count} OSC messages, got {len(self.sent)}: "
                    f"{self.sent!r}"
                )
            time.sleep(0.01)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)


@pytest.fixture
def osc_recorder() -> Iterator[OscRecorder]:
    """Yield a running :class:`OscRecorder` bound to an ephemeral port."""
    recorder = OscRecorder()
    try:
        yield recorder
    finally:
        recorder.close()


def _osc_args(recorder: OscRecorder, port: int, *cli_argv: str) -> list[str]:
    """Build a full ``vrcpilot osc`` argv aimed at ``recorder``.

    ``--button-hold 0.0`` keeps tap-style tests under wall-clock budget
    without patching ``time.sleep`` (which is a banned mock target).
    """
    del recorder
    return [
        "osc",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--button-hold",
        "0.0",
        *cli_argv,
    ]


# ---------------------------------------------------------------------------
# osc send (typed primitives)
# ---------------------------------------------------------------------------


class TestOscSend:
    @pytest.mark.parametrize("truthy", ["true", "1"])
    def test_bool_true_sends_int_one(self, osc_recorder: OscRecorder, truthy: str):
        argv = _osc_args(
            osc_recorder, osc_recorder.port, "send", "/foo", "--bool", truthy
        )
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/foo", (1,))]

    @pytest.mark.parametrize("falsy", ["false", "0"])
    def test_bool_false_sends_int_zero(self, osc_recorder: OscRecorder, falsy: str):
        argv = _osc_args(
            osc_recorder, osc_recorder.port, "send", "/foo", "--bool", falsy
        )
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/foo", (0,))]

    def test_int_in_range(self, osc_recorder: OscRecorder):
        argv = _osc_args(osc_recorder, osc_recorder.port, "send", "/foo", "--int", "42")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/foo", (42,))]

    def test_int_out_of_range_exits_1(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(
            osc_recorder, osc_recorder.port, "send", "/foo", "--int", "256"
        )
        assert main(argv) == 1
        # The validation runs before any datagram is built.
        assert osc_recorder.sent == []
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_float_in_range(self, osc_recorder: OscRecorder):
        argv = _osc_args(
            osc_recorder, osc_recorder.port, "send", "/foo", "--float", "0.5"
        )
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/foo", (pytest.approx(0.5),))]

    def test_float_out_of_range_exits_1(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(
            osc_recorder, osc_recorder.port, "send", "/foo", "--float", "2.0"
        )
        assert main(argv) == 1
        assert osc_recorder.sent == []
        assert "vrcpilot:" in capsys.readouterr().err

    def test_requires_a_type_flag(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "send", "/foo")
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_rejects_multiple_type_flags(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(
            osc_recorder,
            osc_recorder.port,
            "send",
            "/foo",
            "--bool",
            "1",
            "--int",
            "1",
        )
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_silent_on_success(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "send", "/foo", "--int", "1")
        assert main(argv) == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


# ---------------------------------------------------------------------------
# osc axis (InputController float dispatch)
# ---------------------------------------------------------------------------


# Every CLI kebab-case axis name -> the OSC address its method writes to.
# Locks the wiring at the CLI boundary so kebab-case typos and method
# renames are both caught.
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


class TestOscAxis:
    @pytest.mark.parametrize(
        ("name", "expected_address"), list(_AXIS_ADDRESSES.items())
    )
    def test_each_axis_dispatches_to_expected_address(
        self,
        osc_recorder: OscRecorder,
        name: str,
        expected_address: str,
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "axis", name, "0.5")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        address, args = osc_recorder.sent[0]
        assert address == expected_address
        assert args == (pytest.approx(0.5),)

    def test_value_out_of_range_exits_1(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "axis", "vertical", "2.0")
        assert main(argv) == 1
        assert osc_recorder.sent == []
        assert "vrcpilot:" in capsys.readouterr().err

    def test_unknown_name_argparse_error(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "axis", "bogus", "0.0")
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""


# ---------------------------------------------------------------------------
# osc tap (press then release with --button-hold sleep between)
# ---------------------------------------------------------------------------


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


class TestOscTap:
    def test_tap_emits_press_then_release(self, osc_recorder: OscRecorder):
        argv = _osc_args(osc_recorder, osc_recorder.port, "tap", "jump")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(2)
        assert osc_recorder.sent == [
            ("/input/Jump", (1,)),
            ("/input/Jump", (0,)),
        ]

    @pytest.mark.parametrize(("name", "expected_address"), list(_TAP_ADDRESSES.items()))
    def test_each_tap_dispatches_to_expected_address(
        self,
        osc_recorder: OscRecorder,
        name: str,
        expected_address: str,
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "tap", name)
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(2)
        assert osc_recorder.sent == [
            (expected_address, (1,)),
            (expected_address, (0,)),
        ]

    def test_unknown_name_argparse_error(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "tap", "bogus")
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""


# ---------------------------------------------------------------------------
# osc hold (explicit on/off)
# ---------------------------------------------------------------------------


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


class TestOscHold:
    def test_on_sends_one(self, osc_recorder: OscRecorder):
        argv = _osc_args(osc_recorder, osc_recorder.port, "hold", "run", "on")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/input/Run", (1,))]

    def test_off_sends_zero(self, osc_recorder: OscRecorder):
        argv = _osc_args(osc_recorder, osc_recorder.port, "hold", "run", "off")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/input/Run", (0,))]

    @pytest.mark.parametrize(
        ("name", "expected_address"), list(_HOLD_ADDRESSES.items())
    )
    def test_each_hold_name_dispatches(
        self,
        osc_recorder: OscRecorder,
        name: str,
        expected_address: str,
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "hold", name, "on")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [(expected_address, (1,))]

    def test_state_required(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "hold", "run")
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""


# ---------------------------------------------------------------------------
# CLI choice -> InputController method surjection
# ---------------------------------------------------------------------------


class TestOscChoiceCoverage:
    """Every kebab-case CLI choice resolves to a callable on InputController.

    Forward-direction safety net: typos in :data:`AXIS_NAMES` /
    :data:`TAP_NAMES` / :data:`HOLD_NAMES` or method renames on
    :class:`InputController` both fail this. The reverse direction
    (controller methods without a CLI choice) is intentionally NOT
    asserted -- chatbox / typing live outside axis/tap/hold.
    """

    @pytest.mark.parametrize("name", AXIS_NAMES)
    def test_axis_name_resolves_to_callable(self, name: str):
        # Use a UDP socket pointed at a bind-free localhost port; we are
        # only resolving the method, not sending.
        sender = OscSender(host="127.0.0.1", port=1)
        controller = InputController(sender)
        assert callable(getattr(controller, name.replace("-", "_")))

    @pytest.mark.parametrize("name", TAP_NAMES)
    def test_tap_name_resolves_to_callable(self, name: str):
        sender = OscSender(host="127.0.0.1", port=1)
        controller = InputController(sender)
        assert callable(getattr(controller, name.replace("-", "_")))

    @pytest.mark.parametrize("name", HOLD_NAMES)
    def test_hold_name_resolves_to_callable(self, name: str):
        sender = OscSender(host="127.0.0.1", port=1)
        controller = InputController(sender)
        assert callable(getattr(controller, name.replace("-", "_")))


# ---------------------------------------------------------------------------
# osc chatbox / typing
# ---------------------------------------------------------------------------


class TestOscChatbox:
    def test_positional_text_dispatches(self, osc_recorder: OscRecorder):
        argv = _osc_args(osc_recorder, osc_recorder.port, "chatbox", "hello world")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        address, args = osc_recorder.sent[0]
        assert address == "/chatbox/input"
        # Chatbox sends a 3-element bundle (text, send, sfx).
        assert args == ("hello world", True, True)

    def test_no_send_and_no_sfx_flip_flags(self, osc_recorder: OscRecorder):
        argv = _osc_args(
            osc_recorder,
            osc_recorder.port,
            "chatbox",
            "hi",
            "--no-send",
            "--no-sfx",
        )
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent[0] == ("/chatbox/input", ("hi", False, False))

    def test_text_too_long_exits_1(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "chatbox", "x" * 145)
        assert main(argv) == 1
        assert osc_recorder.sent == []
        assert "vrcpilot:" in capsys.readouterr().err

    def test_stdin_text_when_no_positional(
        self,
        osc_recorder: OscRecorder,
        mocker: MockerFixture,
    ):
        # Pipe a string via stdin -- StringIO.isatty() returns False
        # natively, so the chatbox CLI reads it.
        mocker.patch("vrcpilot.cli.osc.sys.stdin", new=io.StringIO("from stdin"))
        argv = _osc_args(osc_recorder, osc_recorder.port, "chatbox")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent[0] == (
            "/chatbox/input",
            ("from stdin", True, True),
        )

    def test_no_text_and_tty_exits_2(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        # The autouse stdin-isatty fixture pins isatty()=True; the
        # chatbox CLI reads it from its own sys.stdin namespace, which
        # shares the same singleton object, so the patch carries over.
        argv = _osc_args(osc_recorder, osc_recorder.port, "chatbox")
        assert main(argv) == 2
        assert osc_recorder.sent == []
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err != ""


class TestOscTyping:
    def test_on_sends_one(self, osc_recorder: OscRecorder):
        argv = _osc_args(osc_recorder, osc_recorder.port, "typing", "on")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/chatbox/typing", (1,))]

    def test_off_sends_zero(self, osc_recorder: OscRecorder):
        argv = _osc_args(osc_recorder, osc_recorder.port, "typing", "off")
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/chatbox/typing", (0,))]

    def test_state_required(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(osc_recorder, osc_recorder.port, "typing")
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""


# ---------------------------------------------------------------------------
# osc avatar (typed avatar parameters)
# ---------------------------------------------------------------------------


class TestOscAvatar:
    @pytest.mark.parametrize(
        ("flag_value", "expected"),
        [("true", 1), ("1", 1), ("false", 0), ("0", 0)],
    )
    def test_bool(
        self,
        osc_recorder: OscRecorder,
        flag_value: str,
        expected: int,
    ):
        argv = _osc_args(
            osc_recorder,
            osc_recorder.port,
            "avatar",
            "MyParam",
            "--bool",
            flag_value,
        )
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/avatar/parameters/MyParam", (expected,))]

    def test_int(self, osc_recorder: OscRecorder):
        argv = _osc_args(
            osc_recorder,
            osc_recorder.port,
            "avatar",
            "MyParam",
            "--int",
            "42",
        )
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent == [("/avatar/parameters/MyParam", (42,))]

    def test_int_out_of_range_exits_1(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(
            osc_recorder,
            osc_recorder.port,
            "avatar",
            "MyParam",
            "--int",
            "256",
        )
        assert main(argv) == 1
        assert osc_recorder.sent == []
        assert "vrcpilot:" in capsys.readouterr().err

    def test_float(self, osc_recorder: OscRecorder):
        argv = _osc_args(
            osc_recorder,
            osc_recorder.port,
            "avatar",
            "MyParam",
            "--float",
            "0.5",
        )
        assert main(argv) == 0
        osc_recorder.wait_for_message_count(1)
        assert osc_recorder.sent[0][0] == "/avatar/parameters/MyParam"
        assert osc_recorder.sent[0][1] == (pytest.approx(0.5),)

    def test_float_out_of_range_exits_1(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        argv = _osc_args(
            osc_recorder,
            osc_recorder.port,
            "avatar",
            "MyParam",
            "--float",
            "2.0",
        )
        assert main(argv) == 1
        assert osc_recorder.sent == []
        assert "vrcpilot:" in capsys.readouterr().err

    def test_invalid_name_exits_1(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        # Slashes in the param name are validated by AvatarParameters
        # before any datagram leaves the process.
        argv = _osc_args(
            osc_recorder,
            osc_recorder.port,
            "avatar",
            "Bad/Name",
            "--bool",
            "1",
        )
        assert main(argv) == 1
        assert osc_recorder.sent == []
        assert "vrcpilot:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Connection plumbing (--host / --port)
# ---------------------------------------------------------------------------


class TestOscConnection:
    def test_host_and_port_route_to_target(self, osc_recorder: OscRecorder):
        # Two recorders on different ports verify that ``--host`` /
        # ``--port`` actually route the UDP datagram (not just propagate
        # into Namespace attrs). We construct a second recorder, send
        # to its port via the CLI, and assert that exactly one server
        # received the message.
        second = OscRecorder()
        try:
            assert (
                main(_osc_args(second, second.port, "send", "/route", "--int", "7"))
                == 0
            )
            second.wait_for_message_count(1)
            assert second.sent == [("/route", (7,))]
            # Make sure nothing leaked to the unrelated recorder.
            assert osc_recorder.sent == []
        finally:
            second.close()


# ---------------------------------------------------------------------------
# Top-level error shape
# ---------------------------------------------------------------------------


class TestOscDispatch:
    def test_no_action_exits_nonzero(
        self,
        osc_recorder: OscRecorder,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``add_subparsers(required=True)`` on the osc parser makes
        # argparse error out when ``vrcpilot osc`` is invoked without
        # an action.
        argv = ["osc", "--port", str(osc_recorder.port)]
        with pytest.raises(SystemExit) as excinfo:
            main(argv)
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""
        # No datagrams escape when argparse rejects the call.
        assert osc_recorder.sent == []


# Sanity check the loopback infrastructure itself so a recorder bug
# does not silently mask CLI regressions.


class TestRecorderSanity:
    """Smoke test the loopback UDP scaffolding."""

    def test_recorder_observes_a_direct_datagram(self, osc_recorder: OscRecorder):
        # Send a raw UDP datagram via socket -- bypasses python-osc on
        # the send side so a regression in OscSender does not flatter
        # the recorder. We just assert that the recorder thread is
        # actually receiving on the bound port.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # A minimal OSC bundle is awkward to hand-assemble; instead
            # use a real python-osc client just for the encoding side.
            from pythonosc.udp_client import SimpleUDPClient

            client = SimpleUDPClient("127.0.0.1", osc_recorder.port)
            client.send_message("/ping", 1)
            osc_recorder.wait_for_message_count(1)
            assert osc_recorder.sent == [("/ping", (1,))]
        finally:
            sock.close()
