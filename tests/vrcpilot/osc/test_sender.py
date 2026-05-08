"""Tests for :mod:`vrcpilot.osc.sender`."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture
from pythonosc.udp_client import SimpleUDPClient

from vrcpilot.osc.avatar import AvatarParameters
from vrcpilot.osc.controller import InputController
from vrcpilot.osc.sender import FLOAT_RANGE, INT_RANGE, OscSender


@pytest.fixture
def mock_client(mocker: MockerFixture):
    """A spec'd ``SimpleUDPClient`` mock for DI into :class:`OscSender`."""
    return mocker.Mock(spec=SimpleUDPClient)


@pytest.fixture
def sender(mock_client) -> OscSender:
    return OscSender(client=mock_client)


class TestConstruction:
    def test_default_host_and_port_are_exposed(self, mock_client):
        s = OscSender(client=mock_client)
        assert s.host == "127.0.0.1"
        assert s.port == 9000

    def test_custom_host_and_port_are_exposed(self, mock_client):
        s = OscSender(host="192.168.1.10", port=9100, client=mock_client)
        assert s.host == "192.168.1.10"
        assert s.port == 9100

    def test_constructs_real_client_when_not_injected(self, mocker: MockerFixture):
        """Without ``client=``, a real ``SimpleUDPClient`` is created with
        host/port."""
        fake = mocker.Mock(spec=SimpleUDPClient)
        ctor = mocker.patch("vrcpilot.osc.sender.SimpleUDPClient", return_value=fake)
        s = OscSender(host="10.0.0.1", port=9123)
        ctor.assert_called_once_with("10.0.0.1", 9123)
        assert s.host == "10.0.0.1"
        assert s.port == 9123


class TestSend:
    def test_forwards_address_and_value_unchanged(self, sender: OscSender, mock_client):
        sender.send("/avatar/parameters/Custom", 9999)
        mock_client.send_message.assert_called_once_with(
            "/avatar/parameters/Custom", 9999
        )

    def test_does_not_validate(self, sender: OscSender, mock_client):
        """``send`` is the documented escape hatch - any value type is forwarded."""
        sender.send("/foo", [1, 2.0, "three", True])
        mock_client.send_message.assert_called_once_with(
            "/foo", [1, 2.0, "three", True]
        )


class TestSendBool:
    @pytest.mark.parametrize(("value", "expected"), [(True, 1), (False, 0)])
    def test_sends_zero_or_one_int(
        self, sender: OscSender, mock_client, value: bool, expected: int
    ):
        sender.send_bool("/input/Run", value)
        mock_client.send_message.assert_called_once_with("/input/Run", expected)


class TestSendInt:
    @pytest.mark.parametrize("value", [0, 1, 128, 254, 255])
    def test_accepts_in_range(self, sender: OscSender, mock_client, value: int):
        sender.send_int("/avatar/parameters/Foo", value)
        mock_client.send_message.assert_called_once_with(
            "/avatar/parameters/Foo", value
        )

    @pytest.mark.parametrize("value", [-1, 256, 1000, -1000])
    def test_rejects_out_of_range(self, sender: OscSender, mock_client, value: int):
        lo, hi = INT_RANGE
        with pytest.raises(
            ValueError,
            match=rf"int value must be in \[{lo}, {hi}\], got {value}",
        ):
            sender.send_int("/avatar/parameters/Foo", value)
        mock_client.send_message.assert_not_called()


class TestSendFloat:
    @pytest.mark.parametrize("value", [-1.0, -0.5, 0.0, 0.5, 1.0])
    def test_accepts_in_range(self, sender: OscSender, mock_client, value: float):
        sender.send_float("/input/Vertical", value)
        mock_client.send_message.assert_called_once_with("/input/Vertical", value)

    @pytest.mark.parametrize("value", [-1.01, 1.01, -2.0, 2.0])
    def test_rejects_out_of_range(self, sender: OscSender, mock_client, value: float):
        lo, hi = FLOAT_RANGE
        with pytest.raises(
            ValueError,
            match=rf"float value must be in \[{lo}, {hi}\], got",
        ):
            sender.send_float("/input/Vertical", value)
        mock_client.send_message.assert_not_called()

    def test_coerces_int_to_float_for_correct_osc_tag(
        self, sender: OscSender, mock_client
    ):
        """``int`` callers (subtype of ``float`` per PEP 484) must still
        produce an OSC ``f`` tag, not ``i``."""
        sender.send_float("/input/Vertical", 1)
        mock_client.send_message.assert_called_once_with("/input/Vertical", 1.0)


class TestControllerFactory:
    def test_returns_input_controller(self, sender: OscSender):
        c = sender.controller()
        assert isinstance(c, InputController)

    def test_returns_fresh_instance_each_call(self, sender: OscSender):
        a = sender.controller()
        b = sender.controller()
        assert a is not b

    def test_button_hold_drives_tap_sleep(
        self, sender: OscSender, mocker: MockerFixture
    ):
        """``button_hold`` is observable via the sleep that ``_tap`` issues."""
        sleep_spy = mocker.patch("vrcpilot.osc.controller.time.sleep")
        c = sender.controller(button_hold=0.25)
        c.jump()
        sleep_spy.assert_called_once_with(0.25)


class TestAvatarParametersFactory:
    def test_returns_avatar_parameters(self, sender: OscSender):
        a = sender.avatar_parameters()
        assert isinstance(a, AvatarParameters)

    def test_returns_fresh_instance_each_call(self, sender: OscSender):
        a = sender.avatar_parameters()
        b = sender.avatar_parameters()
        assert a is not b
