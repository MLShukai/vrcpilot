"""Tests for vrcpilot.mic.devices output-device resolution."""

import sys

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeSoundDevice
from vrcpilot.mic.base import DEVICE_ENV_VAR, MicDeviceNotFoundError
from vrcpilot.mic.devices import (
    default_device_name,
    lookup_output_device,
    resolve_device_name,
)


class TestDefaultDeviceName:
    def test_windows_default_is_cable_input(self, mocker: MockerFixture) -> None:
        mocker.patch.object(sys, "platform", "win32")
        assert default_device_name() == "CABLE Input"

    def test_linux_default_is_vrcpilot_mic(self, mocker: MockerFixture) -> None:
        mocker.patch.object(sys, "platform", "linux")
        assert default_device_name() == "VRCPilotMic"

    def test_macos_has_no_default(self, mocker: MockerFixture) -> None:
        mocker.patch.object(sys, "platform", "darwin")
        assert default_device_name() is None


class TestResolveDeviceName:
    def test_argument_takes_priority_over_env_and_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
    ) -> None:
        monkeypatch.setenv(DEVICE_ENV_VAR, "envname")
        mocker.patch.object(sys, "platform", "win32")
        assert resolve_device_name("argname") == "argname"

    def test_env_used_when_argument_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEVICE_ENV_VAR, "envname")
        assert resolve_device_name(None) == "envname"

    def test_default_used_when_argument_and_env_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
    ) -> None:
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        mocker.patch.object(sys, "platform", "win32")
        assert resolve_device_name(None) == "CABLE Input"

    def test_resolve_uses_linux_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
    ) -> None:
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        mocker.patch.object(sys, "platform", "linux")
        assert resolve_device_name(None) == "VRCPilotMic"

    def test_empty_env_falls_through_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
    ) -> None:
        monkeypatch.setenv(DEVICE_ENV_VAR, "")
        mocker.patch.object(sys, "platform", "win32")
        assert resolve_device_name(None) == "CABLE Input"

    def test_raises_when_no_default_available(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
    ) -> None:
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        mocker.patch.object(sys, "platform", "darwin")
        with pytest.raises(MicDeviceNotFoundError) as exc_info:
            resolve_device_name(None)
        assert DEVICE_ENV_VAR in str(exc_info.value)


class TestLookupOutputDevice:
    @staticmethod
    def _install_fake(mocker: MockerFixture, fake: FakeSoundDevice) -> None:
        mocker.patch.dict(sys.modules, {"sounddevice": fake})

    def test_returns_index_of_first_matching_output_device(
        self, mocker: MockerFixture
    ) -> None:
        fake = FakeSoundDevice()
        fake.add_input_device("Microphone (Realtek)")
        fake.add_output_device("Speakers (Realtek)")
        fake.add_output_device("CABLE Input (VB-Audio Virtual Cable)")
        self._install_fake(mocker, fake)
        assert lookup_output_device("CABLE Input") == 2

    def test_match_is_case_insensitive(self, mocker: MockerFixture) -> None:
        fake = FakeSoundDevice()
        fake.add_output_device("CABLE Input (VB-Audio Virtual Cable)")
        self._install_fake(mocker, fake)
        assert lookup_output_device("cable input") == 0

    def test_first_match_wins_among_multiple(self, mocker: MockerFixture) -> None:
        fake = FakeSoundDevice()
        fake.add_output_device("foo CABLE Input")
        fake.add_output_device("bar CABLE Input")
        self._install_fake(mocker, fake)
        assert lookup_output_device("CABLE Input") == 0

    def test_input_only_device_is_skipped(self, mocker: MockerFixture) -> None:
        fake = FakeSoundDevice()
        fake.add_input_device("CABLE Input recording side")
        fake.add_output_device("CABLE Input render side")
        self._install_fake(mocker, fake)
        assert lookup_output_device("CABLE Input") == 1

    def test_raises_when_no_output_device_matches_on_windows(
        self, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(sys, "platform", "win32")
        fake = FakeSoundDevice()
        fake.add_output_device("Speakers (Realtek)")
        self._install_fake(mocker, fake)
        with pytest.raises(MicDeviceNotFoundError) as exc_info:
            lookup_output_device("CABLE Input")
        msg = str(exc_info.value)
        assert "CABLE Input" in msg
        assert "vb-audio.com/Cable" in msg
        assert "Speakers (Realtek)" in msg

    def test_lookup_error_message_on_linux(self, mocker: MockerFixture) -> None:
        mocker.patch.object(sys, "platform", "linux")
        fake = FakeSoundDevice()
        fake.add_output_device("Built-in Audio Analog Stereo")
        self._install_fake(mocker, fake)
        with pytest.raises(MicDeviceNotFoundError) as exc_info:
            lookup_output_device("VRCPilotMic")
        msg = str(exc_info.value)
        assert "VRCPilotMic" in msg
        assert "vrcpilot linux-mic register" in msg
        assert "vb-audio.com" not in msg
        assert "Built-in Audio Analog Stereo" in msg

    def test_lists_none_when_no_output_devices_present(
        self, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(sys, "platform", "win32")
        fake = FakeSoundDevice()
        fake.add_input_device("Mic only")
        self._install_fake(mocker, fake)
        with pytest.raises(MicDeviceNotFoundError) as exc_info:
            lookup_output_device("CABLE Input")
        assert "(none)" in str(exc_info.value)
