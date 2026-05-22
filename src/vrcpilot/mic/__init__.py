"""Stream float32 PCM into a virtual mic device.

Public surface (every symbol listed below imports on every platform):

* :class:`Mic` -- the session owning the :mod:`soundcard` player.
* :data:`SAMPLE_RATE`, :data:`DEVICE_ENV_VAR`,
  :data:`VIRTUAL_MIC_SINK_NAME`, :func:`default_device_name`.
* :class:`MicDeviceNotFoundError`.

The default device is ``"CABLE Input"`` on Windows (VB-Cable) and
``"VRCPilotMic"`` on Linux after
:func:`vrcpilot.mic.linux.register_virtual_mic`; macOS has no default
and requires ``--device`` / ``$VRCPILOT_MIC_DEVICE``.

Linux-only registration helpers live in :mod:`vrcpilot.mic.linux` and
must be imported from there -- that module raises on import off-Linux.
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
