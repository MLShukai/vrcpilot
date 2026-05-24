"""VRChat OSC send-side client.

Owns the single ``python-osc`` socket and exposes typed send primitives
plus factories for :class:`InputController` / :class:`AvatarParameters`,
which delegate back here to share one validation path.
"""

from __future__ import annotations

from typing import Any

from pythonosc.udp_client import SimpleUDPClient

from . import avatar, controller

#: Inclusive ``[lo, hi]`` range accepted by :meth:`OscSender.send_int`.
INT_RANGE: tuple[int, int] = (0, 255)

#: Inclusive ``[lo, hi]`` range accepted by :meth:`OscSender.send_float`.
FLOAT_RANGE: tuple[float, float] = (-1.0, 1.0)


class OscSender:
    """Single-socket OSC client for VRChat.

    Defaults target a local VRChat with factory OSC settings.

    Typical usage::

        sender = vrcpilot.OscSender()
        sender.controller().jump()
        sender.avatar_parameters().send_bool("MyParam", True)

    Args:
        host: Address VRChat listens on. The default matches VRChat's
            factory OSC config and rarely needs to change.
        port: UDP port VRChat listens on. Default ``9000`` matches the
            factory OSC config.
        client: Test seam — pass a pre-built ``SimpleUDPClient`` (or a
            stand-in) to bypass real UDP construction. ``host`` and
            ``port`` are then only retained for the eponymous
            properties; they no longer influence delivery.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9000,
        *,
        client: SimpleUDPClient | None = None,
    ) -> None:
        self._client = client if client is not None else SimpleUDPClient(host, port)
        self._host = host
        self._port = port

    @property
    def host(self) -> str:
        """Configured remote host (informational; ``client=`` overrides)."""
        return self._host

    @property
    def port(self) -> int:
        """Configured remote port (informational; ``client=`` overrides)."""
        return self._port

    # -- Low-level send -------------------------------------------------

    def send(self, address: str, value: Any) -> None:
        """Pass-through to ``python-osc`` with no normalization."""
        self._client.send_message(address, value)

    def send_bool(self, address: str, value: bool) -> None:
        """Send ``value`` as an OSC int tag (VRChat rejects the bool tag)."""
        self._client.send_message(address, int(bool(value)))

    def send_int(self, address: str, value: int) -> None:
        """Send an int in :data:`INT_RANGE`; raise ``ValueError`` otherwise."""
        lo, hi = INT_RANGE
        if not lo <= value <= hi:
            raise ValueError(f"int value must be in [{lo}, {hi}], got {value}")
        self._client.send_message(address, value)

    def send_float(self, address: str, value: float) -> None:
        """Send a float in :data:`FLOAT_RANGE`; raise ``ValueError``
        otherwise."""
        lo, hi = FLOAT_RANGE
        if not lo <= value <= hi:
            raise ValueError(f"float value must be in [{lo}, {hi}], got {value}")
        # ``int`` is a subtype of ``float`` per PEP 484; without this cast an
        # int caller would land on the OSC ``i`` tag instead of ``f``.
        self._client.send_message(address, float(value))

    # -- High-level views (fresh instance per call) ---------------------

    def controller(self, *, button_hold: float = 0.05) -> controller.InputController:
        """Return a new :class:`InputController` bound to this sender."""
        return controller.InputController(self, button_hold=button_hold)

    def avatar_parameters(self) -> avatar.AvatarParameters:
        """Return a new :class:`AvatarParameters` bound to this sender."""
        return avatar.AvatarParameters(self)
