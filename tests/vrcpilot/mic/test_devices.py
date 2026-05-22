"""Tests for vrcpilot.mic.devices output-device resolution."""

import sys

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeSoundCard, FakeSoundCardSpeaker
from vrcpilot.mic.base import DEVICE_ENV_VAR, MicDeviceNotFoundError
from vrcpilot.mic.devices import (
    default_device_name,
    lookup_speaker,
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


class TestLookupSpeaker:
    @staticmethod
    def _install_fake(mocker: MockerFixture, fake: FakeSoundCard) -> None:
        mocker.patch.dict(sys.modules, {"soundcard": fake})

    def test_returns_first_matching_output_device(self, mocker: MockerFixture) -> None:
        fake = FakeSoundCard()
        fake.add_microphone("Microphone (Realtek)")
        fake.add_speaker("Speakers (Realtek)", id="speakers-realtek")
        fake.add_speaker("CABLE Input (VB-Audio Virtual Cable)", id="cable-input-vb")
        self._install_fake(mocker, fake)
        speaker = lookup_speaker("CABLE Input")
        assert isinstance(speaker, FakeSoundCardSpeaker)
        assert speaker.id == "cable-input-vb"
        assert speaker.name == "CABLE Input (VB-Audio Virtual Cable)"

    def test_match_is_case_insensitive(self, mocker: MockerFixture) -> None:
        fake = FakeSoundCard()
        fake.add_speaker("CABLE Input (VB-Audio Virtual Cable)", id="cable-input")
        self._install_fake(mocker, fake)
        speaker = lookup_speaker("cable input")
        assert speaker.id == "cable-input"

    def test_returns_one_of_the_matches_when_multiple(
        self, mocker: MockerFixture
    ) -> None:
        # ``lookup_speaker`` delegates to ``soundcard.get_speaker`` whose
        # selection among multiple substring hits is implementation-
        # defined (substring + fuzzy id, internal ordering not guaranteed).
        # The contract we own is "returns some matching speaker" -- not
        # which one -- so assert membership rather than identity.
        fake = FakeSoundCard()
        fake.add_speaker("foo CABLE Input", id="first")
        fake.add_speaker("bar CABLE Input", id="second")
        self._install_fake(mocker, fake)
        speaker = lookup_speaker("CABLE Input")
        assert speaker.id in {"first", "second"}

    def test_input_only_device_is_skipped(self, mocker: MockerFixture) -> None:
        # ``all_speakers()`` only returns output devices on soundcard, so
        # microphones registered alongside (input-only) must not appear
        # in the lookup pool even when they share a substring with the
        # needle. The fake mirrors that split.
        fake = FakeSoundCard()
        fake.add_microphone("CABLE Input recording side")
        fake.add_speaker("CABLE Input render side", id="render")
        self._install_fake(mocker, fake)
        speaker = lookup_speaker("CABLE Input")
        assert speaker.id == "render"

    def test_raises_when_no_output_device_matches_on_windows(
        self, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(sys, "platform", "win32")
        fake = FakeSoundCard()
        fake.add_speaker("Speakers (Realtek)", id="speakers-realtek")
        self._install_fake(mocker, fake)
        with pytest.raises(MicDeviceNotFoundError) as exc_info:
            lookup_speaker("CABLE Input")
        msg = str(exc_info.value)
        assert "CABLE Input" in msg
        assert "vb-audio.com/Cable" in msg
        assert "Speakers (Realtek)" in msg

    def test_lookup_error_message_on_linux(self, mocker: MockerFixture) -> None:
        mocker.patch.object(sys, "platform", "linux")
        fake = FakeSoundCard()
        fake.add_speaker("Built-in Audio Analog Stereo", id="built-in-analog-stereo")
        self._install_fake(mocker, fake)
        with pytest.raises(MicDeviceNotFoundError) as exc_info:
            lookup_speaker("VRCPilotMic")
        msg = str(exc_info.value)
        assert "VRCPilotMic" in msg
        assert "vrcpilot linux-mic register" in msg
        assert "vb-audio.com" not in msg
        assert "Built-in Audio Analog Stereo" in msg

    def test_lists_none_when_no_output_devices_present(
        self, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(sys, "platform", "win32")
        fake = FakeSoundCard()
        fake.add_microphone("Mic only")
        self._install_fake(mocker, fake)
        with pytest.raises(MicDeviceNotFoundError) as exc_info:
            lookup_speaker("CABLE Input")
        assert "(none)" in str(exc_info.value)
