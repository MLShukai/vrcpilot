"""Stub for :class:`InputController` - real implementation lands later.

Placeholder so :meth:`vrcpilot.osc.sender.OscSender.controller` has a
resolvable return-type annotation while the full controller is built in
a follow-up commit.
"""

from __future__ import annotations

from . import sender


class InputController:
    """Placeholder for the OSC input-controller view (TBD)."""

    def __init__(self, sender: sender.OscSender, *, button_hold: float = 0.05) -> None:
        self._sender = sender
        self._button_hold = button_hold
