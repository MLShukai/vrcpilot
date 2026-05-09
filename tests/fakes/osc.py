"""OSC-related test doubles.

Boundary fake for ``python-osc``'s :class:`SimpleUDPClient` used by the
``vrcpilot osc`` CLI tests. ``FakeUDPClient`` records every
``send_message(address, value)`` call into ``self.sent`` so tests can
assert what hit the wire without actually opening a UDP socket. The
tests construct a real :class:`vrcpilot.osc.OscSender` with this fake
client injected via the documented ``client=`` DI seam, keeping every
internal collaborator real and only the network boundary swapped out.
"""

from __future__ import annotations


class FakeUDPClient:
    """Recording stand-in for ``pythonosc.udp_client.SimpleUDPClient``.

    Every :meth:`send_message` call appends ``(address, value)`` to
    :attr:`sent` so tests can assert on the exact wire payload. Values
    are typed as :class:`object` because ``OscSender`` forwards the
    caller's value verbatim (``int`` / ``float`` / ``bool`` / etc.).
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    def send_message(self, address: str, value: object) -> None:
        """Record ``(address, value)`` instead of sending over UDP."""
        self.sent.append((address, value))
