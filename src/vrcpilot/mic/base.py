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

#: Shared install hint for libpulse failures.
#:
#: Emitted by both :mod:`vrcpilot.cli.linux_mic` (``status`` probe) and
#: :mod:`vrcpilot.cli.mic` (``OSError`` / ``RuntimeError`` paths) so the
#: wording stays in lock-step. ``libpulse0`` is the Debian/Ubuntu package
#: name; other distros ship the library under different names, hence the
#: generic ``libpulse`` term in the user-facing message.
LIBPULSE_HINT: Final[str] = "install libpulse (e.g. 'sudo apt-get install libpulse0')"


class MicDeviceNotFoundError(RuntimeError):
    """Raised when no output device matches the resolved name.

    Surfaces both the ``soundcard`` miss (no enumerated speaker matches
    the substring/id) and the "no default for this platform" case (macOS
    without ``--device`` / ``$VRCPILOT_MIC_DEVICE``).
    """
