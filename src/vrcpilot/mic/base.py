"""Mic-modality constants and exception types."""

from typing import Final

SAMPLE_RATE: Final[int] = 48000
DEVICE_ENV_VAR: Final[str] = "VRCPILOT_MIC_DEVICE"


class MicDeviceNotFoundError(RuntimeError):
    """Raised when sounddevice cannot find a matching output device."""
