"""Behaviour spec for :class:`vrcpilot.osc.OscSender`.

These are *integration-real* tests: the real
:class:`pythonosc.udp_client.SimpleUDPClient` constructed inside
``OscSender`` sends to a real loopback OSC server (see
``conftest.py``), and assertions are made against the bytes that
actually arrived. The spec is "what VRChat would see on the wire", so
that is exactly what we verify — type tags included.

What is *not* tested here:

* That ``host`` / ``port`` getters echo constructor args. That is a
  trivial round-trip with no defensible spec value (see SKILL.md
  "書かない (marginal value ゼロ)").
* Internal implementation details (which ``python-osc`` API the
  sender happens to call). The boundary is the wire format.
"""

from __future__ import annotations

import pytest

from vrcpilot.osc.sender import FLOAT_RANGE, INT_RANGE, OscSender

from .conftest import LoopbackOsc


class TestSendForwardsRaw:
    """``send`` is the documented escape hatch — no normalization."""

    def test_int_arrives_with_osc_int_tag(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        sender.send("/avatar/parameters/Custom", 9999)
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == "/avatar/parameters/Custom"
        assert args == (9999,)
        # Wire-level type tag must be preserved by the raw escape hatch.
        assert isinstance(args[0], int) and not isinstance(args[0], bool)

    def test_string_arrives_as_string(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        sender.send("/foo", "hello")
        loopback_osc.recorder.wait_for(1)
        assert loopback_osc.recorder.messages[0] == ("/foo", ("hello",))

    def test_list_payload_is_unpacked_into_multiple_args(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        """A list payload becomes a single OSC message with N arguments.

        VRChat's ``/chatbox/input`` uses this — see
        :class:`InputController.chatbox` for the canonical example.
        """
        sender.send("/foo", [1, 2.0, "three", True])
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == "/foo"
        assert args == (1, 2.0, "three", True)


class TestSendBool:
    """``send_bool`` writes the OSC ``i`` tag with 0 or 1.

    VRChat rejects the OSC ``T`` / ``F`` bool tags, so the sender
    must coerce to an int regardless of input truthiness.
    """

    def test_true_arrives_as_int_one(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        sender.send_bool("/input/Run", True)
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == "/input/Run"
        assert args == (1,)
        # bool is a subtype of int in Python; the OSC wire tag must be
        # the plain int ``i`` tag, not the bool ``T`` tag.
        assert isinstance(args[0], int) and not isinstance(args[0], bool)

    def test_false_arrives_as_int_zero(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        sender.send_bool("/input/Run", False)
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == "/input/Run"
        assert args == (0,)
        assert isinstance(args[0], int) and not isinstance(args[0], bool)


class TestSendInt:
    """``send_int`` accepts values within :data:`INT_RANGE` and arrives as
    int."""

    @pytest.mark.parametrize("value", [0, 1, 128, 254, 255])
    def test_value_in_range_arrives_with_int_tag(
        self,
        sender: OscSender,
        loopback_osc: LoopbackOsc,
        value: int,
    ):
        sender.send_int("/avatar/parameters/Foo", value)
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == "/avatar/parameters/Foo"
        assert args == (value,)
        assert isinstance(args[0], int) and not isinstance(args[0], bool)

    @pytest.mark.parametrize("value", [-1, 256, 1000, -1000])
    def test_value_out_of_range_raises_and_nothing_is_sent(
        self,
        sender: OscSender,
        loopback_osc: LoopbackOsc,
        value: int,
    ):
        lo, hi = INT_RANGE
        with pytest.raises(
            ValueError,
            match=rf"int value must be in \[{lo}, {hi}\]",
        ):
            sender.send_int("/avatar/parameters/Foo", value)

        # Validation must happen before the UDP write — no datagram
        # should have escaped to the server.
        with pytest.raises(AssertionError):
            loopback_osc.recorder.wait_for(1, timeout=0.05)


class TestSendFloat:
    """``send_float`` accepts values within :data:`FLOAT_RANGE` and arrives as
    float."""

    @pytest.mark.parametrize("value", [-1.0, -0.5, 0.0, 0.5, 1.0])
    def test_value_in_range_arrives_with_float_tag(
        self,
        sender: OscSender,
        loopback_osc: LoopbackOsc,
        value: float,
    ):
        sender.send_float("/input/Vertical", value)
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == "/input/Vertical"
        assert args == (value,)
        assert isinstance(args[0], float)

    @pytest.mark.parametrize("value", [-1.01, 1.01, -2.0, 2.0])
    def test_value_out_of_range_raises_and_nothing_is_sent(
        self,
        sender: OscSender,
        loopback_osc: LoopbackOsc,
        value: float,
    ):
        lo, hi = FLOAT_RANGE
        with pytest.raises(
            ValueError,
            match=rf"float value must be in \[{lo}, {hi}\]",
        ):
            sender.send_float("/input/Vertical", value)

        with pytest.raises(AssertionError):
            loopback_osc.recorder.wait_for(1, timeout=0.05)

    def test_int_caller_is_coerced_to_float_for_correct_osc_tag(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        """``int`` is a subtype of ``float`` per PEP 484.

        Without the explicit ``float(...)`` coercion in ``send_float``,
        the wire would carry an OSC ``i`` tag — but the spec is "send
        a float", so the wire must carry ``f``.
        """
        sender.send_float("/input/Vertical", 1)
        loopback_osc.recorder.wait_for(1)

        address, args = loopback_osc.recorder.messages[0]
        assert address == "/input/Vertical"
        assert args == (1.0,)
        # The load-bearing assertion: type tag must be ``f``, observable
        # as ``float`` on the receiver.
        assert isinstance(args[0], float)


class TestRoutingToConfiguredEndpoint:
    """The host / port constructor args must control where datagrams go."""

    def test_default_host_and_port_route_to_localhost_9000(self):
        """The defaults document the local VRChat factory OSC settings.

        We don't open a server on 9000 (that would clash with a real
        VRChat). Instead we verify that ``OscSender()`` with defaults
        constructs successfully and exposes ``127.0.0.1`` / ``9000``
        as its configured endpoint — the actual end-to-end routing
        with a custom port is exercised by every other test via the
        ``sender`` fixture.
        """
        s = OscSender()
        # Contract pin: factory-OSC defaults match VRChat's documented
        # listen address. Changing these defaults silently would break
        # every out-of-the-box user.
        assert s.host == "127.0.0.1"
        assert s.port == 9000

    def test_custom_host_and_port_actually_route_there(self, loopback_osc: LoopbackOsc):
        """The end-to-end proof that ``host`` / ``port`` are honoured.

        We do NOT mock ``SimpleUDPClient`` — we open a real loopback
        server on an ephemeral port and confirm the message arrives.
        If the constructor ignored ``port=`` and sent to 9000 instead,
        this test would time out in ``wait_for``.
        """
        s = OscSender(host=loopback_osc.host, port=loopback_osc.port)
        s.send("/probe", 42)
        loopback_osc.recorder.wait_for(1)

        assert loopback_osc.recorder.messages[0] == ("/probe", (42,))


class TestControllerFactory:
    """``OscSender.controller()`` returns a fresh, working view."""

    def test_returns_a_controller_that_actually_sends_to_the_sender_endpoint(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        """End-to-end proof: the controller routes through ``sender``.

        Combines "factory returns the right type" with "the returned
        object is wired to the same UDP socket" into a single
        behavioural assertion. Calling a no-op controller method would
        not detect a wiring bug.
        """
        controller = sender.controller(button_hold=0.0)
        controller.jump()
        loopback_osc.recorder.wait_for(2)  # tap = on + off

        addresses = [m[0] for m in loopback_osc.recorder.messages]
        assert addresses == ["/input/Jump", "/input/Jump"]

    def test_each_call_returns_an_independent_instance(self, sender: OscSender):
        """Two callers must not share mutable controller state.

        The current ``button_hold`` is the only piece of state held by
        a controller, but the spec is "fresh instance per call" — so a
        future caller-specific setting would not leak.
        """
        a = sender.controller()
        b = sender.controller()
        assert a is not b


class TestAvatarParametersFactory:
    """``OscSender.avatar_parameters()`` returns a fresh, working view."""

    def test_returns_a_view_that_actually_sends_to_the_sender_endpoint(
        self, sender: OscSender, loopback_osc: LoopbackOsc
    ):
        view = sender.avatar_parameters()
        view.send_bool("MyBool", True)
        loopback_osc.recorder.wait_for(1)

        assert loopback_osc.recorder.messages[0] == (
            "/avatar/parameters/MyBool",
            (1,),
        )

    def test_each_call_returns_an_independent_instance(self, sender: OscSender):
        a = sender.avatar_parameters()
        b = sender.avatar_parameters()
        assert a is not b
