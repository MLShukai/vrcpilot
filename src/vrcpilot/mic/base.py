"""Mic-modality constants and exception types."""

from typing import Final

SAMPLE_RATE: Final[int] = 48000
DEVICE_ENV_VAR: Final[str] = "VRCPILOT_MIC_DEVICE"

#: Name of the PipeWire virtual mic sink registered by
#: :mod:`vrcpilot.mic.linux`. Linux uses this as the default mic device.
VIRTUAL_MIC_SINK_NAME: Final[str] = "VRCPilotMic"

#: User-facing hint emitted when soundcard fails to load libpulse.
#:
#: Shared between :mod:`vrcpilot.cli.linux_mic` (the ``status`` action's
#: soundcard probe) and :mod:`vrcpilot.cli.mic` (the streaming entry's
#: OSError path) so the wording stays in lock-step. PulseAudio's
#: client shared library ships in the ``libpulse0`` package on Debian
#: / Ubuntu derivatives; other distros surface it under different
#: names but ``libpulse`` is the generic term users can grep for.
LIBPULSE_HINT: Final[str] = "install libpulse (e.g. 'sudo apt-get install libpulse0')"


class MicDeviceNotFoundError(RuntimeError):
    """Raised when soundcard cannot find a matching output device."""
