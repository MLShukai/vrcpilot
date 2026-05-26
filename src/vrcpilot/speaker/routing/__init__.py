"""PID-scoped VRChat audio relay (cross-platform).

Forwards the captured audio of a single VRChat process to a chosen
OS output device by pairing the existing PID-scoped
:class:`vrcpilot.speaker.SpeakerLoop` capture with a :mod:`soundcard`
output player. This is the *routing* side of the speaker subsystem;
``vrcpilot record`` (which writes capture frames to a file) is the
*recording* side and lives in :mod:`vrcpilot.speaker`. See
``docs/virtual-audio.md`` for the user-facing routing playbook and
``memory/specs/pid_speaker_routing_relay.md`` for the contract that
this module implements.

Public surface:

* :class:`AudioDevice` - immutable output device description.
* :func:`list_devices` / :func:`default_device` / :func:`find_device` -
  device enumeration and resolution.
* :class:`Router` / :func:`route` - lifecycle for the capture-to-player
  relay.
* :class:`AudioRoutingError` / :class:`DeviceNotFoundError` - error
  hierarchy.
"""

from __future__ import annotations

from .base import AudioDevice
from .devices import (
    default_device,
    find_device,
    list_devices,
)
from .errors import (
    AudioRoutingError,
    DeviceNotFoundError,
)
from .router import Router, route

__all__ = [
    "AudioDevice",
    "AudioRoutingError",
    "DeviceNotFoundError",
    "Router",
    "default_device",
    "find_device",
    "list_devices",
    "route",
]
