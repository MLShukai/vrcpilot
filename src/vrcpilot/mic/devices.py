"""Output-device resolution for the mic modality.

OS-specific knowledge is confined here: the per-platform default
device-name substring (only Windows + VB-Cable and Linux + PipeWire for
now) and the lazy import of :mod:`soundcard`. :class:`vrcpilot.mic.Mic`
and the CLI consume the resolved ``Speaker`` handle without touching
either.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Final

from vrcpilot.mic.base import (
    DEVICE_ENV_VAR,
    VIRTUAL_MIC_SINK_NAME,
    MicDeviceNotFoundError,
)

# OS-specific default output-device substring. Windows ships with
# VB-Audio Virtual Cable's ``CABLE Input`` and Linux uses the
# ``VRCPilotMic`` PipeWire sink registered by ``vrcpilot.mic.linux``.
# macOS has no convention yet; callers there must pass ``--device`` or
# set ``$VRCPILOT_MIC_DEVICE`` explicitly.
_DEFAULT_DEVICE_BY_PLATFORM: Final[dict[str, str]] = {
    "win32": "CABLE Input",
    "linux": VIRTUAL_MIC_SINK_NAME,
}


def default_device_name() -> str | None:
    """Return the OS-specific default output-device substring.

    ``None`` on platforms without an established virtual-mic
    convention; callers must then receive an explicit device name from
    the user.
    """
    return _DEFAULT_DEVICE_BY_PLATFORM.get(sys.platform)


def resolve_device_name(argument: str | None) -> str:
    """Apply ``argument > $VRCPILOT_MIC_DEVICE > default_device_name()``.

    Raises:
        MicDeviceNotFoundError: All three sources yield nothing (e.g.
            on macOS without explicit configuration).
    """
    if argument is not None:
        return argument
    env = os.environ.get(DEVICE_ENV_VAR)
    if env:
        return env
    default = default_device_name()
    if default is None:
        raise MicDeviceNotFoundError(
            f"no default mic device on this platform; "
            f"pass --device or set ${DEVICE_ENV_VAR}"
        )
    return default


def lookup_speaker(name: str) -> Any:
    """Return the soundcard ``Speaker`` matching ``name``.

    Delegates to :func:`soundcard.get_speaker`, which does a
    case-insensitive substring (and fuzzy id) match and raises
    :class:`LookupError` on miss. ``soundcard`` is imported lazily so
    platforms without ``libpulse`` (Linux) or WASAPI (Windows) wired up
    can still ``import vrcpilot.mic``. The return value is the
    duck-typed ``_Speaker`` instance exposed by :mod:`soundcard`; it
    carries ``id`` / ``name`` / ``channels`` attributes and a
    ``player(samplerate, channels, blocksize=None)`` context-manager
    factory that :class:`Mic` opens.

    Raises:
        MicDeviceNotFoundError: ``soundcard`` reports no match; the
            message lists every output device currently visible and
            points the user at the OS-specific setup step.
    """
    import soundcard as sc  # pyright: ignore[reportMissingTypeStubs]

    try:
        return sc.get_speaker(name)  # pyright: ignore[reportUnknownMemberType]
    except (LookupError, IndexError):
        # soundcard raises LookupError on a clean miss; the fuzzy-match
        # implementation can also surface IndexError when the candidate
        # list is empty. Both map to "no match" for our contract.
        pass

    speakers: list[Any] = list(
        sc.all_speakers()  # pyright: ignore[reportUnknownMemberType]
    )
    listing_lines: list[str] = []
    for s in speakers:
        s_name = str(
            getattr(s, "name", "")  # pyright: ignore[reportUnknownArgumentType]
        )
        s_id = str(
            getattr(s, "id", "")  # pyright: ignore[reportUnknownArgumentType]
        )
        listing_lines.append(f"  {s_name!r} (id={s_id!r})")
    listing = "\n".join(listing_lines)
    if sys.platform == "linux":
        setup_hint = (
            "Run 'vrcpilot linux-mic register' to create the VRCPilotMic "
            "PipeWire sink, "
        )
    else:
        setup_hint = "Install VB-Audio Virtual Cable (https://vb-audio.com/Cable/) "
    raise MicDeviceNotFoundError(
        f"no output device matches {name!r}. "
        f"{setup_hint}or set ${DEVICE_ENV_VAR}.\nAvailable output devices:\n"
        f"{listing or '  (none)'}"
    )
