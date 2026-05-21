"""Tests for :class:`vrcpilot.speaker.sinks.WavFileSink`.

The sink writes a real RIFF/WAV file under ``tmp_path``; assertions go
through the stdlib :mod:`wave` reader so the WAV header and PCM payload
are validated end-to-end without any mocking, matching the
project-wide preference for real I/O over mocks when the dependency is
cheap to exercise (here, a temp-dir WAV file).
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from vrcpilot.speaker.base import CHANNELS, SAMPLE_RATE
from vrcpilot.speaker.sinks import WavFileSink


def _wav_path(tmp_path: Path) -> Path:
    return tmp_path / "out.wav"


def _read_int16_pcm(path: Path) -> np.ndarray:
    """Open ``path`` and return its payload as ``(N, CHANNELS) int16``."""
    with wave.open(str(path), "rb") as reader:
        nframes = reader.getnframes()
        nchannels = reader.getnchannels()
        raw = reader.readframes(nframes)
    return np.frombuffer(raw, dtype=np.int16).reshape(-1, nchannels)


class TestWavFileSinkHappyPath:
    def test_header_matches_format_constants(self, tmp_path: Path):
        path = _wav_path(tmp_path)
        sink = WavFileSink(path)
        sink.write(np.zeros((128, CHANNELS), dtype=np.float32))
        sink.close()

        with wave.open(str(path), "rb") as reader:
            assert reader.getnchannels() == CHANNELS
            assert reader.getsampwidth() == 2
            assert reader.getframerate() == SAMPLE_RATE

    def test_getnframes_matches_sample_count(self, tmp_path: Path):
        path = _wav_path(tmp_path)
        sink = WavFileSink(path)
        sink.write(np.zeros((300, CHANNELS), dtype=np.float32))
        sink.write(np.zeros((400, CHANNELS), dtype=np.float32))
        sink.close()

        assert sink.sample_count == 700
        with wave.open(str(path), "rb") as reader:
            assert reader.getnframes() == 700

    def test_round_trip_preserves_quantised_values(self, tmp_path: Path):
        path = _wav_path(tmp_path)
        # Values strictly inside ``(-1.0, 1.0)`` so clipping is a no-op
        # and the only loss is the float32 -> int16 quantisation step.
        frame = np.array(
            [
                [0.0, 0.0],
                [0.25, -0.25],
                [0.5, -0.5],
                [0.75, -0.75],
            ],
            dtype=np.float32,
        )
        with WavFileSink(path) as sink:
            sink.write(frame)

        info = np.iinfo(np.int16)
        expected = np.clip(frame * float(info.max), info.min, info.max).astype(np.int16)
        pcm = _read_int16_pcm(path)
        assert pcm.shape == (4, CHANNELS)
        np.testing.assert_array_equal(pcm, expected)


class TestWavFileSinkEmptyAndAccumulation:
    def test_empty_frame_is_noop(self, tmp_path: Path):
        path = _wav_path(tmp_path)
        sink = WavFileSink(path)
        sink.write(np.zeros((0, CHANNELS), dtype=np.float32))
        assert sink.sample_count == 0
        sink.close()

        with wave.open(str(path), "rb") as reader:
            assert reader.getnframes() == 0

    def test_sample_count_accumulates_across_writes(self, tmp_path: Path):
        path = _wav_path(tmp_path)
        sink = WavFileSink(path)
        assert sink.sample_count == 0

        sink.write(np.zeros((10, CHANNELS), dtype=np.float32))
        assert sink.sample_count == 10

        sink.write(np.zeros((0, CHANNELS), dtype=np.float32))
        assert sink.sample_count == 10

        sink.write(np.zeros((25, CHANNELS), dtype=np.float32))
        assert sink.sample_count == 35

        sink.close()


class TestWavFileSinkClipping:
    def test_out_of_range_input_clamps_to_int16_extremes(self, tmp_path: Path):
        path = _wav_path(tmp_path)
        # Inputs beyond ``[-1.0, 1.0]`` must clamp to int16 min/max
        # instead of wrapping around.
        frame = np.array(
            [
                [2.0, -2.0],
                [-3.0, 3.0],
            ],
            dtype=np.float32,
        )
        with WavFileSink(path) as sink:
            sink.write(frame)

        info = np.iinfo(np.int16)
        pcm = _read_int16_pcm(path)
        expected = np.array(
            [
                [info.max, info.min],
                [info.min, info.max],
            ],
            dtype=np.int16,
        )
        np.testing.assert_array_equal(pcm, expected)


class TestWavFileSinkValidation:
    @pytest.mark.parametrize(
        "bad_frame",
        [
            np.zeros((4,), dtype=np.float32),  # 1-D
            np.zeros((4, 1), dtype=np.float32),  # mono
            np.zeros((4, 3), dtype=np.float32),  # 3-channel
            np.zeros((2, 2, 2), dtype=np.float32),  # 3-D
        ],
    )
    def test_invalid_shape_raises_value_error(
        self, tmp_path: Path, bad_frame: np.ndarray
    ):
        sink = WavFileSink(_wav_path(tmp_path))
        try:
            with pytest.raises(ValueError):
                sink.write(bad_frame)
        finally:
            sink.close()

    @pytest.mark.parametrize(
        "dtype",
        [np.float64, np.int16, np.int32, np.uint8],
    )
    def test_invalid_dtype_raises_value_error(self, tmp_path: Path, dtype: np.dtype):
        sink = WavFileSink(_wav_path(tmp_path))
        try:
            with pytest.raises(ValueError):
                sink.write(np.zeros((4, CHANNELS), dtype=dtype))
        finally:
            sink.close()


class TestWavFileSinkLifecycle:
    def test_write_after_close_raises_runtime_error(self, tmp_path: Path):
        sink = WavFileSink(_wav_path(tmp_path))
        sink.close()
        with pytest.raises(RuntimeError, match="closed"):
            sink.write(np.zeros((4, CHANNELS), dtype=np.float32))

    def test_close_is_idempotent(self, tmp_path: Path):
        sink = WavFileSink(_wav_path(tmp_path))
        sink.close()
        # Second close must be a quiet no-op rather than an error.
        sink.close()

    def test_context_manager_closes_on_exit(self, tmp_path: Path):
        path = _wav_path(tmp_path)
        with WavFileSink(path) as sink:
            sink.write(np.zeros((8, CHANNELS), dtype=np.float32))

        # After the ``with`` block, the sink must reject further
        # writes -- demonstrates that ``__exit__`` ran ``close``.
        with pytest.raises(RuntimeError, match="closed"):
            sink.write(np.zeros((4, CHANNELS), dtype=np.float32))

        # And the WAV header is finalised so a fresh reader can open
        # and read the previously written frames back.
        with wave.open(str(path), "rb") as reader:
            assert reader.getnframes() == 8

    def test_context_manager_propagates_exception_and_closes(self, tmp_path: Path):
        path = _wav_path(tmp_path)
        sentinel = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            with WavFileSink(path) as sink:
                sink.write(np.zeros((4, CHANNELS), dtype=np.float32))
                raise sentinel

        # ``close`` must still have run despite the propagated error,
        # so the sink rejects subsequent writes.
        with pytest.raises(RuntimeError, match="closed"):
            sink.write(np.zeros((4, CHANNELS), dtype=np.float32))
