"""Tests for :class:`vrcpilot.mic.session.Mic`."""

from __future__ import annotations

import gc
import sys

import numpy as np
import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeSoundDevice
from vrcpilot.mic import Mic
from vrcpilot.mic.base import DEVICE_ENV_VAR, MicDeviceNotFoundError


def _install_fake_with_default_device(mocker: MockerFixture) -> FakeSoundDevice:
    fake = FakeSoundDevice()
    fake.add_output_device("CABLE Input (VB-Audio Virtual Cable)")
    mocker.patch.dict(sys.modules, {"sounddevice": fake})
    mocker.patch.object(sys, "platform", "win32")
    return fake


class TestMicConstruction:
    def test_resolves_default_device_to_cable_input(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        _install_fake_with_default_device(mocker)
        with Mic() as mic:
            assert mic.device_name == "CABLE Input"
            assert mic.device_index == 0

    def test_explicit_device_overrides_default(self, mocker: MockerFixture) -> None:
        fake = FakeSoundDevice()
        fake.add_output_device("Speakers (Realtek)")
        fake.add_output_device("CABLE Input")
        mocker.patch.dict(sys.modules, {"sounddevice": fake})
        with Mic("Speakers") as mic:
            assert mic.device_name == "Speakers"
            assert mic.device_index == 0

    def test_raises_when_device_substring_not_found(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        fake = FakeSoundDevice()
        fake.add_output_device("Speakers (Realtek)")
        mocker.patch.dict(sys.modules, {"sounddevice": fake})
        mocker.patch.object(sys, "platform", "win32")
        with pytest.raises(MicDeviceNotFoundError):
            Mic()

    def test_constructor_opens_and_starts_stream(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic() as _mic:
            assert len(fake.output_streams) == 1
            stream = fake.output_streams[0]
            assert stream.started is True
            assert stream.stopped is False
            assert stream.closed is False
            assert stream.channels == 1
            assert stream.samplerate == 48000
            assert stream.dtype == "float32"
            assert stream.device == 0

    def test_sample_rate_and_channels_baked_into_stream(
        self, mocker: MockerFixture
    ) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic(sample_rate=44100, channels=2) as mic:
            assert mic.sample_rate == 44100
            assert mic.channels == 2
            assert fake.output_streams[0].samplerate == 44100
            assert fake.output_streams[0].channels == 2

    def test_zero_sample_rate_rejected(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        with pytest.raises(ValueError, match="sample_rate"):
            Mic(sample_rate=0)

    def test_zero_channels_rejected(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        with pytest.raises(ValueError, match="channels"):
            Mic(channels=0)


class TestMicPlay:
    def test_single_mono_chunk(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic() as mic:
            mic.play(np.zeros(100, dtype=np.float32))
        out = fake.output_streams[0]
        assert len(out.writes) == 1
        assert out.writes[0].shape == (100,)

    def test_multiple_chunks_share_one_stream(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic() as mic:
            for _ in range(3):
                mic.play(np.zeros(50, dtype=np.float32))
        assert len(fake.output_streams) == 1
        assert len(fake.output_streams[0].writes) == 3

    def test_stereo_mic_accepts_stereo_chunks(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic(channels=2) as mic:
            mic.play(np.zeros((100, 2), dtype=np.float32))
        assert fake.output_streams[0].channels == 2

    def test_non_float32_chunk_raises(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        with Mic() as mic, pytest.raises(ValueError, match="float32"):
            mic.play(np.zeros(10, dtype=np.int16))

    def test_three_dimensional_chunk_raises(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        with Mic() as mic, pytest.raises(ValueError, match="1-D"):
            mic.play(np.zeros((10, 2, 3), dtype=np.float32))

    def test_mono_chunk_into_stereo_mic_raises(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        with Mic(channels=2) as mic, pytest.raises(ValueError, match="channel"):
            mic.play(np.zeros(10, dtype=np.float32))

    def test_stereo_chunk_into_mono_mic_raises(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        with Mic() as mic, pytest.raises(ValueError, match="channel"):
            mic.play(np.zeros((10, 2), dtype=np.float32))

    def test_play_after_close_raises(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        mic = Mic()
        mic.close()
        with pytest.raises(RuntimeError, match="closed"):
            mic.play(np.zeros(10, dtype=np.float32))


class TestMicLifecycle:
    def test_context_exit_stops_and_closes_stream(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic():
            pass
        stream = fake.output_streams[0]
        assert stream.stopped is True
        assert stream.closed is True

    def test_explicit_close_stops_and_closes_stream(
        self, mocker: MockerFixture
    ) -> None:
        fake = _install_fake_with_default_device(mocker)
        mic = Mic()
        mic.close()
        stream = fake.output_streams[0]
        assert stream.stopped is True
        assert stream.closed is True

    def test_close_is_idempotent(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        mic = Mic()
        mic.close()
        mic.close()

    def test_del_closes_stream(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        mic = Mic()
        stream = fake.output_streams[0]
        del mic
        gc.collect()
        assert stream.closed is True

    def test_close_after_failed_construction_is_safe(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No default device available -> resolve_device_name raises
        # before any stream is opened. The unfinished instance's
        # destructor must still cope.
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        fake = FakeSoundDevice()
        mocker.patch.dict(sys.modules, {"sounddevice": fake})
        mocker.patch.object(sys, "platform", "linux")
        with pytest.raises(MicDeviceNotFoundError):
            Mic()
        gc.collect()
        assert fake.output_streams == []
