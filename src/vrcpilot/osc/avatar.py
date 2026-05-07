"""VRChat OSC ``/avatar/parameters/*`` send-side view.

Thin wrapper over :class:`vrcpilot.osc.sender.OscSender` that maps
parameter *names* to the ``/avatar/parameters/<name>`` address space and
delegates the typed send to the same sender. Range validation lives on
:class:`OscSender` (``[0, 255]`` for ints / ``[-1.0, 1.0]`` for floats);
custom avatars that need values outside those ranges should bypass via
``sender.send("/avatar/parameters/Foo", value)``.
"""

from __future__ import annotations

from typing import Final

from . import sender

#: Common prefix prepended to every avatar parameter name.
AVATAR_PARAMETER_PREFIX: Final[str] = "/avatar/parameters/"


class AvatarParameters:
    """View bound to an :class:`OscSender` for avatar-parameter writes.

    Each method takes a parameter *name* (no slashes, non-empty) and
    forwards to the sender's typed primitive. Range validation is
    deferred to :class:`OscSender` so the validation path stays single.
    """

    def __init__(self, sender: sender.OscSender) -> None:
        self._sender = sender

    def send_bool(self, name: str, value: bool) -> None:
        """Send a boolean parameter as VRChat's 0/1 integer convention."""
        self._sender.send_bool(self._address(name), value)

    def send_int(self, name: str, value: int) -> None:
        """Send an integer parameter; range-checked by :class:`OscSender`."""
        self._sender.send_int(self._address(name), value)

    def send_float(self, name: str, value: float) -> None:
        """Send a float parameter; range-checked by :class:`OscSender`."""
        self._sender.send_float(self._address(name), value)

    @staticmethod
    def _address(name: str) -> str:
        """Return ``/avatar/parameters/<name>`` after rejecting bad names."""
        if not name or "/" in name:
            raise ValueError(f"invalid avatar parameter name: {name!r}")
        return AVATAR_PARAMETER_PREFIX + name
