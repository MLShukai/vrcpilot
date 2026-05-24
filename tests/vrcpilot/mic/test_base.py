"""Tests for :mod:`vrcpilot.mic.base`.

Only the cross-module invariants that other code actually depends on
are tested here. Per-platform default-device strings and the env-var
name are covered indirectly by :mod:`tests.vrcpilot.mic.test_devices`
where they are exercised through ``resolve_device_name``.
"""

from __future__ import annotations

import pytest

from vrcpilot.mic.base import SAMPLE_RATE, MicDeviceNotFoundError
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
