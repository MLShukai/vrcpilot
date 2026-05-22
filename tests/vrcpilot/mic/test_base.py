"""Tests for vrcpilot.mic.base constants and exception type."""

import pytest

from vrcpilot.mic.base import (
    DEVICE_ENV_VAR,
    SAMPLE_RATE,
    MicDeviceNotFoundError,
)


class TestConstants:
    def test_sample_rate_matches_speaker_modality(self) -> None:
        assert SAMPLE_RATE == 48000

    def test_device_env_var_uses_vrcpilot_prefix(self) -> None:
        assert DEVICE_ENV_VAR == "VRCPILOT_MIC_DEVICE"


class TestMicDeviceNotFoundError:
    def test_is_subclass_of_runtime_error(self) -> None:
        assert issubclass(MicDeviceNotFoundError, RuntimeError)

    def test_carries_message(self) -> None:
        exc = MicDeviceNotFoundError("not found")
        assert str(exc) == "not found"

    def test_can_be_caught_as_runtime_error(self) -> None:
        with pytest.raises(RuntimeError):
            raise MicDeviceNotFoundError("err")
