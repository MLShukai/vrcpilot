"""Immutable description of an OS output (speaker) device."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """Immutable handle to an OS output speaker.

    Returned by :func:`vrcpilot.speaker.routing.list_devices` /
    :func:`default_device` / :func:`find_device` and accepted by
    :class:`Router`. ``frozen=True`` so a resolved device can be passed
    around safely between threads.

    Attributes:
        id: Backend identifier from :mod:`soundcard` (Windows endpoint
            GUID, PipeWire node identifier). Opaque to callers - treat
            it as a black box and only pass it back into
            :func:`find_device` or :class:`Router`.
        name: User-visible friendly name (FriendlyName on Windows,
            PipeWire ``node.description`` on Linux).
        is_default: ``True`` iff this is the OS default output device.
            At most one device in a single :func:`list_devices` result
            has this flag set.
    """

    id: str
    name: str
    is_default: bool
