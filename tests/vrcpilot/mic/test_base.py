"""Tests for :mod:`vrcpilot.mic.base`.

Only the cross-module invariants that other code actually depends on
are tested here. Per-platform default-device strings and the env-var
name are covered indirectly by :mod:`tests.vrcpilot.mic.test_devices`
where they are exercised through ``resolve_device_name``.
"""

from __future__ import annotations

import pytest

from vrcpilot.mic.base import (
    SAMPLE_RATE,
    MicDeviceNotFoundError,
    config_filename_for,
    description_for,
    sink_name_for,
)
from vrcpilot.speaker.base import SAMPLE_RATE as SPEAKER_SAMPLE_RATE


class TestSampleRate:
    def test_matches_speaker_modality_so_no_resampling_is_needed(self) -> None:
        # The mic and speaker modalities share a host PCM format; if
        # they ever drift, soundcard would be forced to resample on the
        # hot path. The base modules document this coupling, so pin it.
        assert SAMPLE_RATE == SPEAKER_SAMPLE_RATE


class TestMicDeviceNotFoundError:
    def test_can_be_caught_as_runtime_error_so_callers_have_one_baseclass(
        self,
    ) -> None:
        # CLI surfaces both ``MicDeviceNotFoundError`` and the underlying
        # libpulse/WASAPI ``RuntimeError`` through one ``except`` arm;
        # if the inheritance breaks, the CLI would have to grow a
        # second handler.
        with pytest.raises(RuntimeError):
            raise MicDeviceNotFoundError("no device")


# ---------------------------------------------------------------------------
# Suffix naming helpers (sink / description / config-filename)
# ---------------------------------------------------------------------------
#
# These three pure functions are the contract that lets multiple virtual
# mics coexist without name collisions. They are consumed by:
#
# * ``vrcpilot.mic.linux.register_virtual_mic(suffix=...)`` to derive
#   the PipeWire sink name, the PulseAudio description, and the
#   ``pipewire.conf.d/`` fragment filename.
# * The CLI's ``linux-mic register --suffix`` path so what the user
#   types lines up with what ``pactl list`` reports afterwards.
#
# Drift between any two of these three would cause the persistent
# config and the runtime sink (or the CLI display) to refer to
# different names -- a regression that is silent until a user tries to
# select the second mic. The tests below pin all three together.


class TestSinkNameFor:
    def test_empty_suffix_returns_bare_canonical_name(self) -> None:
        # Backward-compat with the original single-sink design: the
        # default suffix must continue to produce ``"VRCPilotMic"`` so
        # existing config files and OSC presets keep working.
        assert sink_name_for("") == "VRCPilotMic"

    def test_alphabetic_suffix_is_appended_with_underscore_separator(self) -> None:
        assert sink_name_for("alt") == "VRCPilotMic_alt"

    def test_alphanumeric_with_dash_and_underscore_is_preserved_verbatim(
        self,
    ) -> None:
        # ``_`` and ``-`` are the only non-alphanumerics that survive
        # normalisation -- they appear in user-chosen profile names and
        # must round-trip exactly so ``pactl list`` matches.
        assert sink_name_for("foo_bar-baz") == "VRCPilotMic_foo_bar-baz"

    @pytest.mark.parametrize(
        "bad_suffix",
        ["bad name", "a/b", "a;b", "a.b", "a:b", "a$b"],
    )
    def test_invalid_characters_raise_value_error(self, bad_suffix: str) -> None:
        # The validation guard is the only thing stopping a typo from
        # silently producing a different sink name than the caller
        # asked for (and the only thing stopping shell-special chars
        # from being injected into the PulseAudio ``module_load``
        # argument string at the call site downstream).
        with pytest.raises(ValueError):
            sink_name_for(bad_suffix)


class TestDescriptionFor:
    def test_empty_suffix_returns_bare_canonical_description(self) -> None:
        # Underscores instead of spaces so the value stays a single
        # PulseAudio token in ``module_load`` arguments (matches the
        # speaker backend's style).
        assert description_for("") == "VRCPilot_Virtual_Mic"

    def test_suffix_is_appended_with_underscore_separator(self) -> None:
        assert description_for("alt") == "VRCPilot_Virtual_Mic_alt"


class TestConfigFilenameFor:
    def test_empty_suffix_returns_bare_canonical_filename(self) -> None:
        # The bare filename must stay ``vrcpilot-mic.conf`` so existing
        # installs are recognised by ``is_registered()`` after the
        # suffix feature ships (no migration required).
        assert config_filename_for("") == "vrcpilot-mic.conf"

    def test_suffix_is_appended_with_hyphen_separator(self) -> None:
        # Hyphen (not underscore) for filenames so they remain a single
        # shell-friendly token and visually match ``vrcpilot-mic.conf``.
        assert config_filename_for("alt") == "vrcpilot-mic-alt.conf"
