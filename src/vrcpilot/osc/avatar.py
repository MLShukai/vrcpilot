"""VRChat OSC ``/avatar/parameters/*`` send-side view.

Range validation lives on :class:`OscSender` (``[0, 255]`` ints,
``[-1.0, 1.0]`` floats); avatars that need values outside those ranges
should bypass via ``sender.send("/avatar/parameters/Foo", value)``.
"""

from __future__ import annotations

from typing import Final

from . import sender

#: Common prefix prepended to every avatar parameter name.
AVATAR_PARAMETER_PREFIX: Final[str] = "/avatar/parameters/"


class AvatarParameters:
    """OSC view bound to an :class:`OscSender` for avatar-parameter writes.

    Each method takes a bare parameter *name* (no slashes, non-empty);
    the ``/avatar/parameters/`` prefix is prepended here.
    """

    def __init__(self, sender: sender.OscSender) -> None:
        self._sender = sender

    def send_bool(self, name: str, value: bool) -> None:
        """Write ``name`` as a bool avatar parameter."""
        self._sender.send_bool(self._address(name), value)

    def send_int(self, name: str, value: int) -> None:
        """Write ``name`` as an int avatar parameter (range-checked
        upstream)."""
        self._sender.send_int(self._address(name), value)

    def send_float(self, name: str, value: float) -> None:
        """Write ``name`` as a float avatar parameter (range-checked
        upstream)."""
        self._sender.send_float(self._address(name), value)

    @staticmethod
    def _address(name: str) -> str:
        """Return ``/avatar/parameters/<name>`` after rejecting bad names."""
        if not name or "/" in name:
            raise ValueError(f"invalid avatar parameter name: {name!r}")
        return AVATAR_PARAMETER_PREFIX + name
