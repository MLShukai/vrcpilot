"""Stream float32 PCM into a virtual mic device.

Public API:

* :class:`Mic` -- session bound to a virtual-cable output device.
* :func:`play` -- module-level convenience over ``Mic(...).play(stream)``.
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

__all__ = [
    "DEVICE_ENV_VAR",
    "MicDeviceNotFoundError",
    "SAMPLE_RATE",
]
