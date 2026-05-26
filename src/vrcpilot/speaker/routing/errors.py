"""Exception hierarchy for :mod:`vrcpilot.speaker.routing`.

``AudioRoutingError`` is the package-wide base; ``DeviceNotFoundError``
is the dedicated subclass for zero-hit device resolutions. Callers that
want a single ``except`` clause for any routing failure should catch
``AudioRoutingError``.
"""

from __future__ import annotations


class AudioRoutingError(RuntimeError):
    """Base error for all :mod:`vrcpilot.speaker.routing` failures.

    Direct instances are raised when device resolution is *ambiguous*
    (two or more devices match a query in the same stage of
    :func:`find_device`). Zero-hit resolutions raise the
    :class:`DeviceNotFoundError` subclass instead.
    """


class DeviceNotFoundError(AudioRoutingError):
    """No output device matched the requested resolution.

    Raised by :func:`find_device` when all three resolution stages
    return zero hits, and by :func:`default_device` when the host has
    no output device at all. Subclass of :class:`AudioRoutingError`,
    so a broad routing-error handler catches this too.
    """
