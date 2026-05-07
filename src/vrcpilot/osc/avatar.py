"""Stub for :class:`AvatarParameters` - real implementation lands later.

Placeholder so :meth:`vrcpilot.osc.sender.OscSender.avatar_parameters`
has a resolvable return-type annotation while the full avatar
parameter view is built in a follow-up commit.
"""

from __future__ import annotations

from . import sender


class AvatarParameters:
    """Placeholder for the OSC avatar-parameter view (TBD)."""

    def __init__(self, sender: sender.OscSender) -> None:
        self._sender = sender
