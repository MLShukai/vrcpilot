"""Tests for :class:`vrcpilot.mic.session.Mic`."""

from __future__ import annotations

import gc
import sys

import numpy as np
import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeSoundCard
from vrcpilot.mic import Mic
from vrcpilot.mic.base import DEVICE_ENV_VAR, MicDeviceNotFoundError


def _install_fake_with_default_device(mocker: MockerFixture) -> FakeSoundCard:
    fake = FakeSoundCard()
    fake.add_speaker("CABLE Input (VB-Audio Virtual Cable)", id="cable-input-vb")
    mocker.patch.dict(sys.modules, {"soundcard": fake})
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
            assert mic.device_id == "cable-input-vb"

    def test_explicit_device_overrides_default(self, mocker: MockerFixture) -> None:
        fake = FakeSoundCard()
        fake.add_speaker("Speakers (Realtek)", id="speakers-realtek")
        fake.add_speaker("CABLE Input", id="cable-input")
        mocker.patch.dict(sys.modules, {"soundcard": fake})
        with Mic("Speakers") as mic:
            assert mic.device_name == "Speakers"
            assert mic.device_id == "speakers-realtek"

    def test_raises_when_device_substring_not_found(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        fake = FakeSoundCard()
        fake.add_speaker("Speakers (Realtek)")
        mocker.patch.dict(sys.modules, {"soundcard": fake})
        mocker.patch.object(sys, "platform", "win32")
        with pytest.raises(MicDeviceNotFoundError):
            Mic()

    def test_constructor_opens_player_with_configured_format(
        self, mocker: MockerFixture
    ) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic() as _mic:
            speaker = fake.speakers[0]
            assert len(speaker.players) == 1
            player_cm = speaker.players[0]
            player = player_cm._player  # noqa: SLF001 -- fake-internal inspection
            assert player.samplerate == 48000
            assert player.channels == 1
            assert player.closed is False

    def test_sample_rate_and_channels_baked_into_player(
        self, mocker: MockerFixture
    ) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic(sample_rate=44100, channels=2) as mic:
            assert mic.sample_rate == 44100
            assert mic.channels == 2
            player = fake.speakers[0].players[0]._player  # noqa: SLF001
            assert player.samplerate == 44100
            assert player.channels == 2

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
        player = fake.speakers[0].players[0]._player  # noqa: SLF001
        assert len(player.writes) == 1
        assert player.writes[0].shape == (100,)

    def test_multiple_chunks_share_one_player(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic() as mic:
            for _ in range(3):
                mic.play(np.zeros(50, dtype=np.float32))
        speaker = fake.speakers[0]
        assert len(speaker.players) == 1
        player = speaker.players[0]._player  # noqa: SLF001
        assert len(player.writes) == 3

    def test_stereo_mic_accepts_stereo_chunks(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic(channels=2) as mic:
            mic.play(np.zeros((100, 2), dtype=np.float32))
        player = fake.speakers[0].players[0]._player  # noqa: SLF001
        assert player.channels == 2

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
    def test_context_exit_closes_player(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        with Mic():
            pass
        player = fake.speakers[0].players[0]._player  # noqa: SLF001
        assert player.closed is True

    def test_explicit_close_closes_player(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        mic = Mic()
        mic.close()
        player = fake.speakers[0].players[0]._player  # noqa: SLF001
        assert player.closed is True

    def test_close_is_idempotent(self, mocker: MockerFixture) -> None:
        _install_fake_with_default_device(mocker)
        mic = Mic()
        mic.close()
        mic.close()

    def test_del_closes_player(self, mocker: MockerFixture) -> None:
        fake = _install_fake_with_default_device(mocker)
        mic = Mic()
        player = fake.speakers[0].players[0]._player  # noqa: SLF001
        del mic
        gc.collect()
        assert player.closed is True

    def test_close_after_failed_construction_is_safe(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No default device available -> resolve_device_name raises
        # before any player is opened. The unfinished instance's
        # destructor must still cope.
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        fake = FakeSoundCard()
        mocker.patch.dict(sys.modules, {"soundcard": fake})
        mocker.patch.object(sys, "platform", "linux")
        with pytest.raises(MicDeviceNotFoundError):
            Mic()
        gc.collect()
        # No speakers means no players could ever be opened.
        assert fake.speakers == []
