"""Immutable description of an OS output (speaker) device."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """Immutable handle to an OS output speaker.

    Attributes:
        id: Backend identifier (Windows endpoint GUID, PipeWire node id).
        name: User-visible friendly name.
        is_default: ``True`` if this is the OS default output device.
    """

    id: str
    name: str
    is_default: bool
