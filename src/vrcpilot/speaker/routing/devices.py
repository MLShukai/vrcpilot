"""Output-device enumeration / resolution via :mod:`soundcard`.

Confines the un-typed ``soundcard`` surface so the public API never
leaks ``Any``. Resolution in :func:`find_device` is a strict three-stage
sequence (id exact -> name exact -> name substring); any stage that
finds more than one match raises :class:`AudioRoutingError` immediately
rather than falling through, which makes ambiguous queries fail loudly.
"""

from __future__ import annotations

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


def _enumerate() -> tuple[list[AudioDevice], str | None]:
    """Return all visible output devices plus the default device id.

    Returned list is unordered (caller sorts per F1.2). The default id
    is ``None`` only when no output device is available.
    """
    import soundcard as sc  # pyright: ignore[reportMissingTypeStubs]

    speakers: list[Any] = list(
        sc.all_speakers()  # pyright: ignore[reportUnknownMemberType]
    )
    default_id: str | None
    try:
        default_speaker: Any = sc.default_speaker()  # pyright: ignore[reportUnknownMemberType]
        default_id = str(default_speaker.id)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    except (RuntimeError, IndexError, LookupError):
        # No default device available (e.g. zero output devices). Treat
        # as "no default" rather than propagating soundcard's internal
        # error variety; list_devices() must still return [] cleanly.
        default_id = None
    devices = [_to_audio_device(sp, default_id) for sp in speakers]
    return devices, default_id


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
    devices, _ = _enumerate()
    return _sorted(devices)


def default_device() -> AudioDevice:
    """Return the OS default output device.

    Raises:
        DeviceNotFoundError: No output device exists on this system.
        ImportError: ``soundcard`` is not installed.
        OSError: ``soundcard`` cannot load libpulse / WASAPI.
    """
    devices, default_id = _enumerate()
    if default_id is None or not devices:
        raise DeviceNotFoundError("no output device available on this system")
    for device in devices:
        if device.id == default_id:
            return device
    # Soundcard reported a default id that is missing from
    # all_speakers() - treat the system as having no usable default.
    raise DeviceNotFoundError("no output device available on this system")


def _raise_ambiguous(query: str, segment: str, matches: list[AudioDevice]) -> None:
    listing = _format_listing(matches)
    raise AudioRoutingError(
        f"multiple output devices match {query!r} (segment={segment}):\n"
        f"{listing}\n"
        "Use a more specific query (full id or exact name)."
    )


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

    id_hits = [d for d in devices if d.id == query]
    if len(id_hits) == 1:
        return id_hits[0]
    if len(id_hits) >= 2:
        _raise_ambiguous(query, "id-exact", id_hits)

    name_hits = [d for d in devices if d.name == query]
    if len(name_hits) == 1:
        return name_hits[0]
    if len(name_hits) >= 2:
        _raise_ambiguous(query, "name-exact", name_hits)

    needle = query.lower()
    sub_hits = [d for d in devices if needle in d.name.lower()]
    if len(sub_hits) == 1:
        return sub_hits[0]
    if len(sub_hits) >= 2:
        _raise_ambiguous(query, "name-substring", sub_hits)

    listing = _format_listing(devices)
    raise DeviceNotFoundError(
        f"no output device matches {query!r}. " f"Available output devices:\n{listing}"
    )
