"""Tests for :mod:`vrcpilot.osc.sender`."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture
from pythonosc.udp_client import SimpleUDPClient

from vrcpilot.osc.avatar import AvatarParameters
from vrcpilot.osc.controller import InputController
from vrcpilot.osc.sender import FLOAT_RANGE, INT_RANGE, OscSender, SupportsBool
from vrcpilot.process import OscConfig


@pytest.fixture
def mock_client(mocker: MockerFixture):
    """A spec'd ``SimpleUDPClient`` mock for DI into :class:`OscSender`."""
    return mocker.Mock(spec=SimpleUDPClient)


@pytest.fixture
def sender(mock_client) -> OscSender:
    return OscSender(client=mock_client)


# ---------------------------------------------------------------------------
# Construction / properties
# ---------------------------------------------------------------------------


def test_default_host_and_port_are_exposed(mock_client) -> None:
    s = OscSender(client=mock_client)
    assert s.host == "127.0.0.1"
    assert s.port == 9000


def test_custom_host_and_port_are_exposed(mock_client) -> None:
    s = OscSender(host="192.168.1.10", port=9100, client=mock_client)
    assert s.host == "192.168.1.10"
    assert s.port == 9100


def test_constructs_real_client_when_not_injected(mocker: MockerFixture) -> None:
    """Without ``client=``, a real ``SimpleUDPClient`` is created with
    host/port."""
    fake = mocker.Mock(spec=SimpleUDPClient)
    ctor = mocker.patch("vrcpilot.osc.sender.SimpleUDPClient", return_value=fake)
    s = OscSender(host="10.0.0.1", port=9123)
    ctor.assert_called_once_with("10.0.0.1", 9123)
    assert s.host == "10.0.0.1"
    assert s.port == 9123


# ---------------------------------------------------------------------------
# send (passthrough)
# ---------------------------------------------------------------------------


def test_send_forwards_address_and_value_unchanged(
    sender: OscSender, mock_client
) -> None:
    sender.send("/avatar/parameters/Custom", 9999)
    mock_client.send_message.assert_called_once_with("/avatar/parameters/Custom", 9999)


def test_send_does_not_validate(sender: OscSender, mock_client) -> None:
    """``send`` is the documented escape hatch - any value type is forwarded."""
    sender.send("/foo", [1, 2.0, "three", True])
    mock_client.send_message.assert_called_once_with("/foo", [1, 2.0, "three", True])


# ---------------------------------------------------------------------------
# send_bool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, 1),
        (False, 0),
        (1, 1),
        (0, 0),
        (3, 1),  # truthy non-bool int still goes via bool()
        ("", 0),  # empty container/string is falsy
        ("x", 1),
    ],
)
def test_send_bool_normalizes_to_int_zero_or_one(
    sender: OscSender, mock_client, value: object, expected: int
) -> None:
    sender.send_bool("/input/Run", value)  # type: ignore[arg-type]
    mock_client.send_message.assert_called_once_with("/input/Run", expected)


def test_supports_bool_protocol_is_runtime_checkable() -> None:
    """Custom objects with ``__bool__`` satisfy the protocol."""

    class Truthy:
        def __bool__(self) -> bool:
            return True

    assert isinstance(Truthy(), SupportsBool)


# ---------------------------------------------------------------------------
# send_int
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 1, 128, 254, 255])
def test_send_int_accepts_in_range(sender: OscSender, mock_client, value: int) -> None:
    sender.send_int("/avatar/parameters/Foo", value)
    mock_client.send_message.assert_called_once_with("/avatar/parameters/Foo", value)


@pytest.mark.parametrize("value", [-1, 256, 1000, -1000])
def test_send_int_rejects_out_of_range(
    sender: OscSender, mock_client, value: int
) -> None:
    lo, hi = INT_RANGE
    with pytest.raises(
        ValueError,
        match=rf"int value must be in \[{lo}, {hi}\], got {value}",
    ):
        sender.send_int("/avatar/parameters/Foo", value)
    mock_client.send_message.assert_not_called()


def test_send_int_coerces_supports_int(sender: OscSender, mock_client) -> None:
    """Non-int objects implementing ``__int__`` are coerced before
    validation."""

    class IntLike:
        def __int__(self) -> int:
            return 42

    sender.send_int("/avatar/parameters/Foo", IntLike())
    mock_client.send_message.assert_called_once_with("/avatar/parameters/Foo", 42)


# ---------------------------------------------------------------------------
# send_float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [-1.0, -0.5, 0.0, 0.5, 1.0])
def test_send_float_accepts_in_range(
    sender: OscSender, mock_client, value: float
) -> None:
    sender.send_float("/input/Vertical", value)
    mock_client.send_message.assert_called_once_with("/input/Vertical", value)


@pytest.mark.parametrize("value", [-1.01, 1.01, -2.0, 2.0])
def test_send_float_rejects_out_of_range(
    sender: OscSender, mock_client, value: float
) -> None:
    lo, hi = FLOAT_RANGE
    with pytest.raises(
        ValueError,
        match=rf"float value must be in \[{lo}, {hi}\], got",
    ):
        sender.send_float("/input/Vertical", value)
    mock_client.send_message.assert_not_called()


def test_send_float_coerces_int_to_float(sender: OscSender, mock_client) -> None:
    sender.send_float("/input/Vertical", 1)  # int satisfies SupportsFloat
    mock_client.send_message.assert_called_once_with("/input/Vertical", 1.0)


# ---------------------------------------------------------------------------
# Factories: controller / avatar_parameters
# ---------------------------------------------------------------------------


def test_controller_returns_input_controller(sender: OscSender) -> None:
    c = sender.controller()
    assert isinstance(c, InputController)


def test_controller_returns_fresh_instance_each_call(sender: OscSender) -> None:
    a = sender.controller()
    b = sender.controller()
    assert a is not b


def test_controller_forwards_button_hold(sender: OscSender) -> None:
    c = sender.controller(button_hold=0.25)
    # ``_button_hold`` is private but is the parameter the spec promises
    # to forward; this is the only externally observable side effect here.
    assert c._button_hold == 0.25  # noqa: SLF001


def test_avatar_parameters_returns_avatar_parameters(sender: OscSender) -> None:
    a = sender.avatar_parameters()
    assert isinstance(a, AvatarParameters)


def test_avatar_parameters_returns_fresh_instance_each_call(
    sender: OscSender,
) -> None:
    a = sender.avatar_parameters()
    b = sender.avatar_parameters()
    assert a is not b


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


def test_from_config_uses_in_port_and_localhost(mocker: MockerFixture) -> None:
    fake = mocker.Mock(spec=SimpleUDPClient)
    ctor = mocker.patch("vrcpilot.osc.sender.SimpleUDPClient", return_value=fake)
    s = OscSender.from_config(OscConfig(in_port=9100))
    assert s.host == "127.0.0.1"
    assert s.port == 9100
    ctor.assert_called_once_with("127.0.0.1", 9100)


def test_from_config_default_port(mocker: MockerFixture) -> None:
    mocker.patch(
        "vrcpilot.osc.sender.SimpleUDPClient",
        return_value=mocker.Mock(spec=SimpleUDPClient),
    )
    s = OscSender.from_config(OscConfig())
    assert s.host == "127.0.0.1"
    assert s.port == 9000
