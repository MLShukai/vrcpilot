"""VRChat OSC send-side client package."""

from __future__ import annotations

from .sender import OscSender, SupportsBool

__all__ = [
    "OscSender",
    "SupportsBool",
]
