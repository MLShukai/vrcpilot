"""Exception hierarchy for :mod:`vrcpilot.speaker.routing`.

``AudioRoutingError`` is the package-wide base; ``DeviceNotFoundError``
is the dedicated subclass for zero-hit device resolutions.
"""

from __future__ import annotations


class AudioRoutingError(RuntimeError):
    """Base error for all :mod:`vrcpilot.speaker.routing` failures."""


class DeviceNotFoundError(AudioRoutingError):
    """No output device matched the requested resolution."""
