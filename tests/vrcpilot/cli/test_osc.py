"""Tests for :mod:`vrcpilot.cli.osc` (commit 1: skeleton + ``send``).

The CLI calls into :mod:`vrcpilot.osc` via the
:func:`vrcpilot.cli.osc._make_sender` factory. Patching that factory
to return an :class:`~vrcpilot.osc.OscSender` constructed with an
injected :class:`~tests.fakes.FakeUDPClient` keeps every internal
collaborator real (validation, dispatch, forwarding) while swapping
out the UDP boundary. ``FakeUDPClient`` is therefore the single
boundary fake for this suite.
"""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeUDPClient
from vrcpilot.cli import main
from vrcpilot.osc import OscSender


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
