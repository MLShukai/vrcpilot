"""Mic-modality constants and exception types shared across submodules."""

from typing import Final

#: Default playback rate in Hz. Matches VRChat's microphone input rate so
#: the libpulse / WASAPI path can pass float32 through without resampling.
SAMPLE_RATE: Final[int] = 48000

#: Env var overriding the resolved output-device substring; consulted
#: after the explicit ``--device`` argument and before the OS default.
DEVICE_ENV_VAR: Final[str] = "VRCPILOT_MIC_DEVICE"

#: PipeWire sink name registered by :mod:`vrcpilot.mic.linux` and the
#: Linux default for :func:`vrcpilot.mic.default_device_name`.
VIRTUAL_MIC_SINK_NAME: Final[str] = "VRCPilotMic"

#: Shared install hint for libpulse failures. Kept in one place so the
#: ``status`` probe in :mod:`vrcpilot.cli.linux_mic` and the
#: ``OSError`` / ``RuntimeError`` paths in :mod:`vrcpilot.cli.mic` stay
#: in lock-step.
LIBPULSE_HINT: Final[str] = "install libpulse (e.g. 'sudo apt-get install libpulse0')"


class MicDeviceNotFoundError(RuntimeError):
    """Raised when no output device matches the resolved name.

    Covers both the ``soundcard`` miss and the "no default for this
    platform" case (macOS without ``--device`` / ``$VRCPILOT_MIC_DEVICE``).
    Hint at ``vrcpilot linux-mic register`` on Linux or VB-Cable on
    Windows when surfacing this to users.
    """
