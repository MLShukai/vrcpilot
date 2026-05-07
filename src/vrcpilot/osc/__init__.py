"""VRChat OSC send-side client package."""

from __future__ import annotations

from .avatar import AvatarParameters
from .controller import InputController
from .sender import OscSender

__all__ = [
    "AvatarParameters",
    "InputController",
    "OscSender",
]
