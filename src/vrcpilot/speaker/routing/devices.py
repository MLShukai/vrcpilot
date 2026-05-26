"""Output-device enumeration / resolution via :mod:`soundcard`.

Confines the un-typed ``soundcard`` surface so the public API never
leaks ``Any``. Resolution in :func:`find_device` is a strict three-stage
sequence (id exact -> name exact -> name substring); any stage that
finds more than one match raises :class:`AudioRoutingError` immediately
rather than falling through, which makes ambiguous queries fail loudly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vrcpilot.speaker.routing.base import AudioDevice
from vrcpilot.speaker.routing.errors import (
    AudioRoutingError,
    DeviceNotFoundError,
)


def _to_audio_device(speaker: Any, default_id: str | None) -> AudioDevice:
    """Convert a ``soundcard.Speaker`` to :class:`AudioDevice`.

    ``soundcard`` lacks type stubs, so the attribute reads are typed
    locally and the public return stays :class:`AudioDevice`.
    """
    sid: str = str(speaker.id)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    name: str = str(speaker.name)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    return AudioDevice(id=sid, name=name, is_default=(sid == default_id))


def _enumerate() -> list[AudioDevice]:
    """Return all visible output devices (unordered).

    Returns ``[]`` when no output device is available; never raises for
    that case (F1.4). The OS default is identified by comparing each
    speaker id against ``sc.default_speaker().id``; when no default
    exists the resulting list simply has no ``is_default == True`` entry.
    """
    import soundcard as sc  # pyright: ignore[reportMissingTypeStubs]

    speakers: list[Any] = list(
        sc.all_speakers()  # pyright: ignore[reportUnknownMemberType]
    )
    try:
        default_speaker: Any = sc.default_speaker()  # pyright: ignore[reportUnknownMemberType]
        default_id: str | None = str(default_speaker.id)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    except (RuntimeError, IndexError, LookupError):
        # No default device available (e.g. zero output devices). Treat
        # as "no default" rather than propagating soundcard's internal
        # error variety; list_devices() must still return [] cleanly.
        default_id = None
    return [_to_audio_device(sp, default_id) for sp in speakers]


def _sorted(devices: list[AudioDevice]) -> list[AudioDevice]:
    """Apply F1.2 ordering: default first, then ``name`` ascending."""
    # Python's default str comparison is codepoint-order and
    # case-sensitive, which matches the spec verbatim.
    return sorted(devices, key=lambda d: (not d.is_default, d.name))


def _format_listing(devices: list[AudioDevice]) -> str:
    if not devices:
        return "  (none)"
    return "\n".join(f"  {d.name!r} (id={d.id!r})" for d in devices)


def list_devices() -> list[AudioDevice]:
    """Return every visible output device.

    Ordering: the OS default (if any) is first, followed by remaining
    devices sorted by ``name`` ascending (Python's default codepoint
    comparison). Returns ``[]`` when no output device exists; never
    raises for that case.

    Raises:
        ImportError: ``soundcard`` is not installed.
        OSError: ``soundcard`` cannot load libpulse / WASAPI.
    """
    return _sorted(_enumerate())


def default_device() -> AudioDevice:
    """Return the OS default output device.

    Raises:
        DeviceNotFoundError: No output device exists on this system.
        ImportError: ``soundcard`` is not installed.
        OSError: ``soundcard`` cannot load libpulse / WASAPI.
    """
    for device in _enumerate():
        if device.is_default:
            return device
    raise DeviceNotFoundError("no output device available on this system")


# A resolution stage: a name (for error messages) plus the predicate
# that filters ``list_devices()`` for matches in that stage.
_Stage = tuple[str, Callable[[AudioDevice], bool]]


def _resolve_stage(
    query: str,
    segment: str,
    devices: list[AudioDevice],
    predicate: Callable[[AudioDevice], bool],
) -> AudioDevice | None:
    """Run one resolution stage; return the unique hit or ``None``.

    Raises :class:`AudioRoutingError` if the stage matches >= 2 devices
    so the caller never falls through to the next stage on ambiguity
    (F1.7).
    """
    hits = [d for d in devices if predicate(d)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) >= 2:
        listing = _format_listing(hits)
        raise AudioRoutingError(
            f"multiple output devices match {query!r} (segment={segment}):\n"
            f"{listing}\n"
            "Use a more specific query (full id or exact name)."
        )
    return None


def find_device(query: str) -> AudioDevice:
    """Resolve ``query`` to a single output device.

    Resolution stages (each stops on a unique hit; multiple hits at any
    stage raise immediately without falling through):

    1. ``query == device.id`` exact match.
    2. ``query == device.name`` exact match (case-sensitive).
    3. ``query.lower() in device.name.lower()`` substring match.

    Raises:
        AudioRoutingError: Any stage matched two or more devices.
        DeviceNotFoundError: All three stages matched zero devices.
        ImportError: ``soundcard`` is not installed.
        OSError: ``soundcard`` cannot load libpulse / WASAPI.
    """
    devices = list_devices()
    needle = query.lower()
    stages: tuple[_Stage, ...] = (
        ("id-exact", lambda d: d.id == query),
        ("name-exact", lambda d: d.name == query),
        ("name-substring", lambda d: needle in d.name.lower()),
    )
    for segment, predicate in stages:
        hit = _resolve_stage(query, segment, devices, predicate)
        if hit is not None:
            return hit

    listing = _format_listing(devices)
    raise DeviceNotFoundError(
        f"no output device matches {query!r}. Available output devices:\n{listing}"
    )
