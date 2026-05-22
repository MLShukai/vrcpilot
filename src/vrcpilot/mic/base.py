"""Mic-modality constants and exception types."""

from typing import Final

SAMPLE_RATE: Final[int] = 48000
DEVICE_ENV_VAR: Final[str] = "VRCPILOT_MIC_DEVICE"

#: Name of the PipeWire virtual mic sink registered by
#: :mod:`vrcpilot.mic.linux`. Linux uses this as the default mic device.
VIRTUAL_MIC_SINK_NAME: Final[str] = "VRCPilotMic"


class MicDeviceNotFoundError(RuntimeError):
    """Raised when soundcard cannot find a matching output device."""
