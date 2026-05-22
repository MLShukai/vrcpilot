"""Stream float32 PCM into a virtual mic device.

Public API:

* :class:`Mic` -- session bound to a virtual-cable output device. Owns
  the underlying sounddevice OutputStream; :meth:`Mic.play` writes one
  chunk at a time and the caller drives the loop.
* :data:`SAMPLE_RATE`, :data:`DEVICE_ENV_VAR`, :func:`default_device_name`
* :class:`MicDeviceNotFoundError`

The module imports on every platform. The default device name is
platform-specific (``"CABLE Input"`` on Windows; absent on Linux/macOS,
where ``--device`` / ``$VRCPILOT_MIC_DEVICE`` is required).
"""

from vrcpilot.mic.base import (
    DEVICE_ENV_VAR,
    SAMPLE_RATE,
    MicDeviceNotFoundError,
)
from vrcpilot.mic.devices import default_device_name
from vrcpilot.mic.session import Mic

__all__ = [
    "DEVICE_ENV_VAR",
    "Mic",
    "MicDeviceNotFoundError",
    "SAMPLE_RATE",
    "default_device_name",
]
