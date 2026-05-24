"""Behaviour spec for :class:`vrcpilot.osc.AvatarParameters`.

Integration-real via loopback UDP — see :mod:`tests.vrcpilot.osc.conftest`.
We verify what arrives on the wire after the prefix is applied and after
the underlying ``OscSender`` does its range / type coercion. No
``OscSender`` mock is involved: the spec is "this is what reaches
VRChat", and the canonical send path produces that.
"""

from __future__ import annotations

import pytest

from vrcpilot.osc.avatar import AVATAR_PARAMETER_PREFIX, AvatarParameters
from vrcpilot.osc.sender import OscSender

from .conftest import LoopbackOsc


@pytest.fixture
def avatars(sender: OscSender) -> AvatarParameters:
    return AvatarParameters(sender)


class TestPrefixContract:
    """Pin the documented prefix — VRChat will not route any other path."""

    def test_avatar_parameter_prefix_is_the_vrchat_documented_path(self):
        # Contract pin: every send_* prepends this string verbatim. Any
        # change here breaks every avatar parameter write in the wild.
        assert AVATAR_PARAMETER_PREFIX == "/avatar/parameters/"


class TestSendBool:
    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("MyBool", True),
            ("Grounded", False),
            ("X", True),
        ],
    )
    def test_send_bool_writes_int_zero_or_one_at_prefixed_address(
        self,
        avatars: AvatarParameters,
        loopback_osc: LoopbackOsc,
        name: str,
        value: bool,
    ):
        avatars.send_bool(name, value)
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == AVATAR_PARAMETER_PREFIX + name
        assert args == (1 if value else 0,)
        # VRChat rejects the OSC bool tag — must be int on the wire.
        assert isinstance(args[0], int) and not isinstance(args[0], bool)

    @pytest.mark.parametrize("bad_name", ["", "foo/bar", "/foo", "foo/", "a/b/c"])
    def test_send_bool_rejects_names_with_slashes_or_empty_name(
        self,
        avatars: AvatarParameters,
        loopback_osc: LoopbackOsc,
        bad_name: str,
    ):
        """Names that would corrupt the address path must be rejected.

        ``""`` would produce ``/avatar/parameters/`` (no parameter
        name); ``"foo/bar"`` would create a fake nested namespace.
        Either silently sent would land at the wrong VRChat parameter
        slot.
        """
        with pytest.raises(ValueError, match="invalid avatar parameter name"):
            avatars.send_bool(bad_name, True)

        # Validation must happen before the UDP write.
        with pytest.raises(AssertionError):
            loopback_osc.recorder.wait_for(1, timeout=0.05)


class TestSendInt:
    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("MyInt", 42),
            ("VRCEmote", 0),
            ("Grounded_state", 255),
        ],
    )
    def test_send_int_writes_int_at_prefixed_address(
        self,
        avatars: AvatarParameters,
        loopback_osc: LoopbackOsc,
        name: str,
        value: int,
    ):
        avatars.send_int(name, value)
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == AVATAR_PARAMETER_PREFIX + name
        assert args == (value,)
        assert isinstance(args[0], int) and not isinstance(args[0], bool)

    def test_send_int_propagates_sender_range_error(
        self, avatars: AvatarParameters, loopback_osc: LoopbackOsc
    ):
        """The [0, 255] range guard lives on ``OscSender`` — confirm the avatar
        view does not silently swallow it.

        We pass a value outside the range; the wrapper must surface
        the ``ValueError`` raised by the sender so callers learn about
        bad data, and no datagram must escape.
        """
        with pytest.raises(ValueError, match="int value must be in"):
            avatars.send_int("Foo", 999)

        with pytest.raises(AssertionError):
            loopback_osc.recorder.wait_for(1, timeout=0.05)

    @pytest.mark.parametrize("bad_name", ["", "foo/bar"])
    def test_send_int_rejects_invalid_name(
        self,
        avatars: AvatarParameters,
        loopback_osc: LoopbackOsc,
        bad_name: str,
    ):
        with pytest.raises(ValueError, match="invalid avatar parameter name"):
            avatars.send_int(bad_name, 1)

        with pytest.raises(AssertionError):
            loopback_osc.recorder.wait_for(1, timeout=0.05)


class TestSendFloat:
    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("MyFloat", 0.5),
            ("VRCFaceBlendH", -1.0),
            ("VRCFaceBlendV", 1.0),
        ],
    )
    def test_send_float_writes_float_at_prefixed_address(
        self,
        avatars: AvatarParameters,
        loopback_osc: LoopbackOsc,
        name: str,
        value: float,
    ):
        avatars.send_float(name, value)
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == AVATAR_PARAMETER_PREFIX + name
        assert args == (value,)
        # OSC ``f`` tag - the avatar view must not corrupt the type.
        assert isinstance(args[0], float)

    def test_send_float_propagates_sender_range_error(
        self, avatars: AvatarParameters, loopback_osc: LoopbackOsc
    ):
        with pytest.raises(ValueError, match="float value must be in"):
            avatars.send_float("Foo", 2.0)

        with pytest.raises(AssertionError):
            loopback_osc.recorder.wait_for(1, timeout=0.05)

    @pytest.mark.parametrize("bad_name", ["", "foo/bar"])
    def test_send_float_rejects_invalid_name(
        self,
        avatars: AvatarParameters,
        loopback_osc: LoopbackOsc,
        bad_name: str,
    ):
        with pytest.raises(ValueError, match="invalid avatar parameter name"):
            avatars.send_float(bad_name, 0.5)

        with pytest.raises(AssertionError):
            loopback_osc.recorder.wait_for(1, timeout=0.05)


class TestNameWhitelist:
    """Names without slashes (any other character is fine) round-trip."""

    @pytest.mark.parametrize(
        "good_name",
        ["VRCEmote", "Grounded_state", "X", "param-1", "Foo.Bar", "a"],
    )
    def test_well_formed_name_is_passed_through_to_address(
        self,
        avatars: AvatarParameters,
        loopback_osc: LoopbackOsc,
        good_name: str,
    ):
        """Catches over-strict validation that would reject legal names.

        VRChat parameter names allow letters, digits, underscores,
        dashes, and dots. The only rejection criteria are "empty" and
        "contains ``/``" (which would break the address path).
        """
        avatars.send_bool(good_name, True)
        loopback_osc.recorder.wait_for(1)

        address, _args = loopback_osc.recorder.messages[0]
        assert address == AVATAR_PARAMETER_PREFIX + good_name
