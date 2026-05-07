"""Tests for :mod:`vrcpilot.osc.avatar`."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from vrcpilot.osc.avatar import AVATAR_PARAMETER_PREFIX, AvatarParameters
from vrcpilot.osc.sender import OscSender


@pytest.fixture
def sender_mock(mocker: MockerFixture):
    """A spec'd :class:`OscSender` mock for asserting view delegation."""
    return mocker.Mock(spec=OscSender)


@pytest.fixture
def avatars(sender_mock) -> AvatarParameters:
    return AvatarParameters(sender_mock)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_avatar_parameter_prefix_value() -> None:
    """Regression guard: prefix must stay ``/avatar/parameters/``."""
    assert AVATAR_PARAMETER_PREFIX == "/avatar/parameters/"


# ---------------------------------------------------------------------------
# Delegation: each method forwards address + value to the sender
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MyBool", True),
        ("Grounded", False),
        ("X", True),
    ],
)
def test_send_bool_forwards_to_sender_send_bool(
    avatars: AvatarParameters, sender_mock, name: str, value: bool
) -> None:
    avatars.send_bool(name, value)
    sender_mock.send_bool.assert_called_once_with(AVATAR_PARAMETER_PREFIX + name, value)
    sender_mock.send_int.assert_not_called()
    sender_mock.send_float.assert_not_called()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MyInt", 42),
        ("VRCEmote", 0),
        ("Grounded_state", 255),
    ],
)
def test_send_int_forwards_to_sender_send_int(
    avatars: AvatarParameters, sender_mock, name: str, value: int
) -> None:
    avatars.send_int(name, value)
    sender_mock.send_int.assert_called_once_with(AVATAR_PARAMETER_PREFIX + name, value)
    sender_mock.send_bool.assert_not_called()
    sender_mock.send_float.assert_not_called()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MyFloat", 0.5),
        ("VRCFaceBlendH", -1.0),
        ("VRCFaceBlendV", 1.0),
    ],
)
def test_send_float_forwards_to_sender_send_float(
    avatars: AvatarParameters, sender_mock, name: str, value: float
) -> None:
    avatars.send_float(name, value)
    sender_mock.send_float.assert_called_once_with(
        AVATAR_PARAMETER_PREFIX + name, value
    )
    sender_mock.send_bool.assert_not_called()
    sender_mock.send_int.assert_not_called()


def test_send_bool_passes_value_through_unchanged(
    avatars: AvatarParameters, sender_mock
) -> None:
    """The view should not normalize the bool itself; OscSender does
    ``int(bool(...))`` once, centrally."""
    sentinel = object()
    avatars.send_bool("Foo", sentinel)  # type: ignore[arg-type]
    sender_mock.send_bool.assert_called_once_with(
        AVATAR_PARAMETER_PREFIX + "Foo", sentinel
    )


# ---------------------------------------------------------------------------
# Validation propagation: ValueError from OscSender bubbles up
# ---------------------------------------------------------------------------


def test_send_int_propagates_sender_range_error(
    avatars: AvatarParameters, sender_mock
) -> None:
    sender_mock.send_int.side_effect = ValueError("int value must be in [0, 255]")
    with pytest.raises(ValueError, match="int value must be in"):
        avatars.send_int("Foo", 999)


def test_send_float_propagates_sender_range_error(
    avatars: AvatarParameters, sender_mock
) -> None:
    sender_mock.send_float.side_effect = ValueError(
        "float value must be in [-1.0, 1.0]"
    )
    with pytest.raises(ValueError, match="float value must be in"):
        avatars.send_float("Foo", 2.0)


# ---------------------------------------------------------------------------
# Name validation: empty / contains '/' → ValueError, observed via send_*
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_name", ["", "foo/bar", "/foo", "foo/", "a/b/c"])
def test_send_bool_rejects_invalid_name(
    avatars: AvatarParameters, sender_mock, bad_name: str
) -> None:
    with pytest.raises(ValueError, match="invalid avatar parameter name"):
        avatars.send_bool(bad_name, True)
    sender_mock.send_bool.assert_not_called()


@pytest.mark.parametrize("bad_name", ["", "foo/bar"])
def test_send_int_rejects_invalid_name(
    avatars: AvatarParameters, sender_mock, bad_name: str
) -> None:
    with pytest.raises(ValueError, match="invalid avatar parameter name"):
        avatars.send_int(bad_name, 1)
    sender_mock.send_int.assert_not_called()


@pytest.mark.parametrize("bad_name", ["", "foo/bar"])
def test_send_float_rejects_invalid_name(
    avatars: AvatarParameters, sender_mock, bad_name: str
) -> None:
    with pytest.raises(ValueError, match="invalid avatar parameter name"):
        avatars.send_float(bad_name, 0.5)
    sender_mock.send_float.assert_not_called()


@pytest.mark.parametrize(
    "good_name", ["VRCEmote", "Grounded_state", "X", "param-1", "Foo.Bar", "a"]
)
def test_valid_names_pass_through(
    avatars: AvatarParameters, sender_mock, good_name: str
) -> None:
    avatars.send_bool(good_name, True)
    sender_mock.send_bool.assert_called_once_with(
        AVATAR_PARAMETER_PREFIX + good_name, True
    )
