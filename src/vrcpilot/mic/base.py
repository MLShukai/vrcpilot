"""Mic-modality constants and exception types shared across submodules."""

from typing import Final

#: Default playback rate in Hz. Matches VRChat's microphone input rate so
#: the libpulse / WASAPI path can pass float32 through without resampling.
SAMPLE_RATE: Final[int] = 48000

#: Env var overriding the resolved output-device substring; consulted
#: after the explicit ``--device`` argument and before the OS default.
DEVICE_ENV_VAR: Final[str] = "VRCPILOT_MIC_DEVICE"

#: PipeWire sink name registered by :mod:`vrcpilot.mic.linux` and the
#: Linux default for :func:`vrcpilot.mic.default_device_name`. Suffixed
#: sinks are derived from this via :func:`sink_name_for`.
VIRTUAL_MIC_SINK_NAME: Final[str] = "VRCPilotMic"

#: Shared install hint for libpulse failures. Kept in one place so the
#: ``status`` probe in :mod:`vrcpilot.cli.linux_mic` and the
#: ``OSError`` / ``RuntimeError`` paths in :mod:`vrcpilot.cli.mic` stay
#: in lock-step.
LIBPULSE_HINT: Final[str] = "install libpulse (e.g. 'sudo apt-get install libpulse0')"


def sink_name_for(suffix: str = "") -> str:
    """Return the PipeWire sink name for ``suffix``.

    Empty / whitespace-only suffix returns the bare
    :data:`VIRTUAL_MIC_SINK_NAME` (``"VRCPilotMic"``). A non-empty
    suffix produces ``f"VRCPilotMic_{suffix}"`` so multiple virtual
    mics can coexist without name collisions. Raises ``ValueError``
    for suffixes containing characters outside ``[A-Za-z0-9_-]``.
    """
    normalized = _normalize_suffix(suffix)
    if not normalized:
        return VIRTUAL_MIC_SINK_NAME
    return f"{VIRTUAL_MIC_SINK_NAME}_{normalized}"


def description_for(suffix: str = "") -> str:
    """Return the PulseAudio ``device.description`` for ``suffix``.

    Empty suffix returns ``"VRCPilot_Virtual_Mic"``; non-empty returns
    ``f"VRCPilot_Virtual_Mic_{suffix}"``. Underscores instead of spaces
    keep the value a single PulseAudio token (matches the speaker
    backend's style and avoids quoting headaches in ``module_load``
    argument strings).
    """
    normalized = _normalize_suffix(suffix)
    if not normalized:
        return "VRCPilot_Virtual_Mic"
    return f"VRCPilot_Virtual_Mic_{normalized}"


def config_filename_for(suffix: str = "") -> str:
    """Return the ``pipewire.conf.d/`` filename for ``suffix``.

    Empty suffix returns ``"vrcpilot-mic.conf"``; non-empty returns
    ``f"vrcpilot-mic-{suffix}.conf"`` (hyphen separator so the filename
    stays a single shell-friendly token).
    """
    normalized = _normalize_suffix(suffix)
    if not normalized:
        return "vrcpilot-mic.conf"
    return f"vrcpilot-mic-{normalized}.conf"


def _normalize_suffix(suffix: str) -> str:
    """Strip ``suffix`` and validate against ``[A-Za-z0-9_-]``.

    Empty / whitespace-only inputs normalise to ``""``. Any other
    character raises ``ValueError`` so a typo cannot silently produce
    a different sink name than the caller expected.
    """
    if not suffix:
        return ""
    stripped = suffix.strip()
    if not stripped:
        return ""
    if not all(c.isalnum() or c in "-_" for c in stripped):
        raise ValueError(
            f"suffix must contain only alphanumerics, '-', or '_' (got {suffix!r})"
        )
    return stripped


class MicDeviceNotFoundError(RuntimeError):
    """Raised when no output device matches the resolved name.

    Covers both the ``soundcard`` miss and the "no default for this
    platform" case (macOS without ``--device`` / ``$VRCPILOT_MIC_DEVICE``).
    Hint at ``vrcpilot linux-mic register`` on Linux or VB-Cable on
    Windows when surfacing this to users.
    """
