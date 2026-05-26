"""Stream float32 PCM into a virtual mic device.

Default device: ``"CABLE Input"`` on Windows (VB-Cable),
``"VRCPilotMic"`` on Linux after
:func:`vrcpilot.mic.linux.register_virtual_mic`. macOS has no default
and requires ``--device`` / ``$VRCPILOT_MIC_DEVICE``.

Linux-only registration helpers live in :mod:`vrcpilot.mic.linux`,
which raises on import off-Linux.
"""

from vrcpilot.mic.base import (
    DEVICE_ENV_VAR,
    SAMPLE_RATE,
    VIRTUAL_MIC_SINK_NAME,
    MicDeviceNotFoundError,
)
from vrcpilot.mic.devices import default_device_name
from vrcpilot.mic.session import Mic

__all__ = [
    "DEVICE_ENV_VAR",
    "Mic",
    "MicDeviceNotFoundError",
    "SAMPLE_RATE",
    "VIRTUAL_MIC_SINK_NAME",
    "default_device_name",
]
