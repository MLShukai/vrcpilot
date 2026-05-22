"""Tests for vrcpilot.mic.session.Mic and module-level play helper."""

from __future__ import annotations

import sys

import numpy as np
import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeSoundDevice
from vrcpilot.mic import Mic, play
from vrcpilot.mic.base import DEVICE_ENV_VAR, MicDeviceNotFoundError


def _install_fake_with_default_device(mocker: MockerFixture) -> FakeSoundDevice:
    fake = FakeSoundDevice()
    fake.add_output_device("CABLE Input (VB-Audio Virtual Cable)")
    mocker.patch.dict(sys.modules, {"sounddevice": fake})
    mocker.patch.object(sys, "platform", "win32")
    return fake


class TestMicConstruction:
    def test_resolves_default_device_to_cable_input(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        _install_fake_with_default_device(mocker)
        mic = Mic()
        assert mic.device_name == "CABLE Input"
        assert mic.device_index == 0

    def test_explicit_device_overrides_default(self, mocker: MockerFixture) -> None:
        fake = FakeSoundDevice()
        fake.add_output_device("Speakers (Realtek)")
        fake.add_output_device("CABLE Input")
        mocker.patch.dict(sys.modules, {"sounddevice": fake})
        mic = Mic("Speakers")
        assert mic.device_name == "Speakers"
        assert mic.device_index == 0

    def test_raises_when_device_substring_not_found(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        fake = FakeSoundDevice()
        fake.add_output_device("Speakers (Realtek)")
        mocker.patch.dict(sys.modules, {"sounddevice": fake})
        mocker.patch.object(sys, "platform", "win32")
        with pytest.raises(MicDeviceNotFoundError):
            Mic()


class TestMicPlay:
    def test_empty_stream_is_noop(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        Mic().play(iter([]))
        assert fake.output_streams == []

    def test_single_mono_chunk_opens_one_channel_stream(
        self, mocker: MockerFixture
    ) -> None:
        fake = _install_fake_with_default_device(mocker)
        chunk = np.zeros(100, dtype=np.float32)
        Mic().play([chunk])
        assert len(fake.output_streams) == 1
        out = fake.output_streams[0]
        assert out.channels == 1
        assert out.samplerate == 48000
        assert out.dtype == "float32"
        assert out.device == 0
        assert len(out.writes) == 1
        assert out.closed is True

    def test_stereo_chunk_opens_two_channel_stream(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        chunk = np.zeros((100, 2), dtype=np.float32)
        Mic().play([chunk])
        assert fake.output_streams[0].channels == 2

    def test_multiple_chunks_share_one_output_stream(
        self, mocker: MockerFixture
    ) -> None:
        fake = _install_fake_with_default_device(mocker)
        chunks = [np.zeros(50, dtype=np.float32) for _ in range(3)]
        Mic().play(chunks)
        assert len(fake.output_streams) == 1
        assert len(fake.output_streams[0].writes) == 3

    def test_custom_sample_rate_forwarded(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        Mic().play([np.zeros(10, dtype=np.float32)], sample_rate=44100)
        assert fake.output_streams[0].samplerate == 44100

    def test_non_float32_chunk_raises(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        with pytest.raises(ValueError, match="float32"):
            Mic().play([np.zeros(10, dtype=np.int16)])

    def test_three_dimensional_chunk_raises(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        with pytest.raises(ValueError, match="1-D"):
            Mic().play([np.zeros((10, 2, 3), dtype=np.float32)])

    def test_channel_mismatch_across_chunks_raises(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        first = np.zeros((10, 2), dtype=np.float32)
        second = np.zeros((10, 1), dtype=np.float32)
        with pytest.raises(ValueError, match="channel"):
            Mic().play([first, second])

    def test_output_stream_drained_after_play_returns(
        self, mocker: MockerFixture
    ) -> None:
        fake = _install_fake_with_default_device(mocker)
        Mic().play([np.zeros(10, dtype=np.float32)])
        assert fake.output_streams[0].closed is True


class TestModuleLevelPlay:
    def test_play_creates_mic_and_opens_stream(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        play([np.zeros(10, dtype=np.float32)])
        assert len(fake.output_streams) == 1

    def test_play_forwards_device_argument(self, mocker: MockerFixture) -> None:
        fake = FakeSoundDevice()
        fake.add_output_device("Speakers")
        fake.add_output_device("CABLE Input")
        mocker.patch.dict(sys.modules, {"sounddevice": fake})
        play([np.zeros(10, dtype=np.float32)], device="CABLE Input")
        assert fake.output_streams[0].device == 1

    def test_play_forwards_sample_rate(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        play([np.zeros(10, dtype=np.float32)], sample_rate=22050)
        assert fake.output_streams[0].samplerate == 22050
