"""Output-device resolution for the mic modality.

Confines per-platform default-device knowledge and the lazy
:mod:`soundcard` import so :class:`vrcpilot.mic.Mic` and the CLI can
work with an already-resolved ``Speaker`` handle.
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
    """OS-specific default output-device substring, or ``None``.

    ``None`` on platforms without an established virtual-mic convention
    (e.g. macOS); callers must surface "explicit device required" then.
    """
    return _DEFAULT_DEVICE_BY_PLATFORM.get(sys.platform)


def resolve_device_name(argument: str | None) -> str:
    """Resolve ``argument > $VRCPILOT_MIC_DEVICE > default_device_name()``.

    Raises ``MicDeviceNotFoundError`` if all three sources yield nothing.
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

    Delegates to :func:`soundcard.get_speaker` (case-insensitive
    substring + fuzzy id); the id path matters because PipeWire surfaces
    the virtual sink as ``id="VRCPilotMic"`` /
    ``name="VRCPilot_Virtual_Mic"``. ``soundcard`` is imported lazily so
    the package stays importable on hosts without libpulse / WASAPI.

    Raises:
        MicDeviceNotFoundError: No match; the message lists every
            visible output device and the OS-specific setup hint.
        ImportError: ``soundcard`` is not installed.
        OSError: ``soundcard`` cannot dlopen libpulse / WASAPI.
    """
    import soundcard as sc  # pyright: ignore[reportMissingTypeStubs]

    try:
        return sc.get_speaker(name)  # pyright: ignore[reportUnknownMemberType]
    except LookupError:
        # Re-raise below as MicDeviceNotFoundError with a listing so the
        # user sees what *is* available (soundcard's LookupError carries
        # only the query string).
        pass

    speakers: list[Any] = list(
        sc.all_speakers()  # pyright: ignore[reportUnknownMemberType]
    )
    listing = "\n".join(
        f"  {speaker.name!r} (id={speaker.id!r})"  # pyright: ignore[reportUnknownMemberType]
        for speaker in speakers
    )
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
