"""Stream float32 PCM into a virtual mic device.

Public API:

* :class:`Mic` -- session bound to a virtual-cable output device. Owns
  the underlying :mod:`soundcard` player; :meth:`Mic.play` writes one
  chunk at a time and the caller drives the loop.
* :data:`SAMPLE_RATE`, :data:`DEVICE_ENV_VAR`,
  :data:`VIRTUAL_MIC_SINK_NAME`, :func:`default_device_name`
* :class:`MicDeviceNotFoundError`

The module imports on every platform. The default device name is
platform-specific (``"CABLE Input"`` on Windows, ``"VRCPilotMic"`` on
Linux after :func:`vrcpilot.mic.linux.register_virtual_mic`; absent on
macOS, where ``--device`` / ``$VRCPILOT_MIC_DEVICE`` is required).

Linux-specific registration helpers (``register_virtual_mic`` /
``unregister_virtual_mic`` / ``is_registered`` / ``RegisterResult``)
live in :mod:`vrcpilot.mic.linux` and must be imported from there --
they raise on import when ``sys.platform != "linux"``.
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
