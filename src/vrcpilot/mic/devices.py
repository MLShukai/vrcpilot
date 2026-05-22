"""Output-device resolution for the mic modality.

OS-specific knowledge is confined here: the per-platform default
device-name substring (only Windows + VB-Cable for now) and the lazy
import of :mod:`sounddevice`. :class:`vrcpilot.mic.Mic` and the CLI
consume the resolved sounddevice index without touching either.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Final

from vrcpilot.mic.base import DEVICE_ENV_VAR, MicDeviceNotFoundError

# OS-specific default output-device substring. Linux / macOS entries
# will be added once a virtual-mic convention is settled; until then
# callers on those platforms must pass ``--device`` or set
# ``$VRCPILOT_MIC_DEVICE`` explicitly.
_DEFAULT_DEVICE_BY_PLATFORM: Final[dict[str, str]] = {
    "win32": "CABLE Input",
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
            on Linux/macOS without explicit configuration).
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


def lookup_output_device(name: str) -> int:
    """Return the sounddevice index of the first output device whose name
    *contains* ``name`` (case-insensitive).

    ``sounddevice`` is imported lazily so platforms without a PortAudio
    binding installed can still ``import vrcpilot.mic``.

    Raises:
        MicDeviceNotFoundError: No output device matches; the message
            lists every output device currently visible to PortAudio.
    """
    import sounddevice as sd  # pyright: ignore[reportMissingTypeStubs]

    devices: list[dict[str, Any]] = list(
        sd.query_devices()  # pyright: ignore[reportUnknownMemberType]
    )
    needle = name.lower()
    for index, info in enumerate(devices):
        if int(info.get("max_output_channels", 0)) <= 0:
            continue
        if needle in str(info.get("name", "")).lower():
            return index
    listing = "\n".join(
        f"  [{i}] {d['name']!r} (out={d.get('max_output_channels', 0)})"
        for i, d in enumerate(devices)
        if int(d.get("max_output_channels", 0)) > 0
    )
    raise MicDeviceNotFoundError(
        f"no output device matches {name!r}. "
        f"Install VB-Audio Virtual Cable (https://vb-audio.com/Cable/) "
        f"or set ${DEVICE_ENV_VAR}.\nAvailable output devices:\n"
        f"{listing or '  (none)'}"
    )
