"""PID-scoped VRChat audio relay (cross-platform).

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

from vrcpilot.speaker.routing.base import AudioDevice
from vrcpilot.speaker.routing.devices import (
    default_device,
    find_device,
    list_devices,
)
from vrcpilot.speaker.routing.errors import (
    AudioRoutingError,
    DeviceNotFoundError,
)
from vrcpilot.speaker.routing.router import Router, route

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
