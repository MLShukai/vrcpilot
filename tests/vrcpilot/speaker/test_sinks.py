"""Tests for :mod:`vrcpilot.speaker.sinks`.

:class:`WavFileSink` writes a real RIFF/WAV file under ``tmp_path``;
assertions go through the stdlib :mod:`wave` reader so the WAV header
and PCM payload are validated end-to-end without any mocking, matching
the project-wide preference for real I/O over mocks when the
dependency is cheap to exercise (here, a temp-dir WAV file).

:class:`RawPcmStdoutSink` is driven against an :class:`io.BytesIO` so
the same quantisation guarantees can be asserted at the byte level
without the WAV header.
"""

from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import numpy as np
import pytest
from pytest_mock import MockerFixture

from vrcpilot.speaker.base import CHANNELS, SAMPLE_RATE
from vrcpilot.speaker.sinks import RawPcmStdoutSink, WavFileSink, _float32_to_int16


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


class TestRawPcmStdoutSinkHappyPath:
    def test_writes_interleaved_int16_little_endian(self):
        # Values strictly inside ``(-1.0, 1.0)`` so clipping is a no-op
        # and only the float32 -> int16 quantisation step is exercised.
        frame = np.array(
            [
                [0.0, 0.0],
                [0.25, -0.25],
                [0.5, -0.5],
                [0.75, -0.75],
            ],
            dtype=np.float32,
        )
        buf = io.BytesIO()
        with RawPcmStdoutSink(stream=buf) as sink:
            sink.write(frame)

        # ``<i2`` (little-endian int16) is enforced so the byte stream
        # is s16le regardless of host endianness.
        expected = _float32_to_int16(frame).astype("<i2").tobytes()
        assert buf.getvalue() == expected
        # 4 frames * 2 channels * 2 bytes per sample.
        assert len(buf.getvalue()) == 4 * 2 * 2

    def test_round_trip_preserves_quantised_values(self):
        frame = np.array(
            [
                [0.1, -0.1],
                [0.3, -0.3],
                [0.6, -0.6],
                [0.9, -0.9],
            ],
            dtype=np.float32,
        )
        buf = io.BytesIO()
        with RawPcmStdoutSink(stream=buf) as sink:
            sink.write(frame)

        decoded = np.frombuffer(buf.getvalue(), dtype="<i2").reshape(-1, CHANNELS)
        np.testing.assert_array_equal(decoded, _float32_to_int16(frame))

    def test_sample_count_matches_frames_written(self):
        buf = io.BytesIO()
        sink = RawPcmStdoutSink(stream=buf)
        sink.write(np.zeros((300, CHANNELS), dtype=np.float32))
        sink.write(np.zeros((400, CHANNELS), dtype=np.float32))
        sink.close()

        assert sink.sample_count == 700


class TestRawPcmStdoutSinkEmptyAndAccumulation:
    def test_empty_frame_is_noop(self):
        buf = io.BytesIO()
        sink = RawPcmStdoutSink(stream=buf)
        sink.write(np.zeros((0, CHANNELS), dtype=np.float32))

        assert sink.sample_count == 0
        assert buf.getvalue() == b""

    def test_sample_count_accumulates_across_writes(self):
        buf = io.BytesIO()
        sink = RawPcmStdoutSink(stream=buf)
        assert sink.sample_count == 0

        sink.write(np.zeros((10, CHANNELS), dtype=np.float32))
        assert sink.sample_count == 10

        sink.write(np.zeros((0, CHANNELS), dtype=np.float32))
        assert sink.sample_count == 10

        sink.write(np.zeros((25, CHANNELS), dtype=np.float32))
        assert sink.sample_count == 35

        sink.close()


class TestRawPcmStdoutSinkClipping:
    def test_out_of_range_input_clamps_to_int16_extremes(self):
        # Inputs beyond ``[-1.0, 1.0]`` must clamp to int16 min/max
        # instead of wrapping around. Mirror of the WavFileSink
        # clipping test against the headerless byte stream.
        frame = np.array(
            [
                [2.0, -2.0],
                [-3.0, 3.0],
            ],
            dtype=np.float32,
        )
        buf = io.BytesIO()
        with RawPcmStdoutSink(stream=buf) as sink:
            sink.write(frame)

        info = np.iinfo(np.int16)
        decoded = np.frombuffer(buf.getvalue(), dtype="<i2").reshape(-1, CHANNELS)
        expected = np.array(
            [
                [info.max, info.min],
                [info.min, info.max],
            ],
            dtype=np.int16,
        )
        np.testing.assert_array_equal(decoded, expected)


class TestRawPcmStdoutSinkValidation:
    @pytest.mark.parametrize(
        "bad_frame",
        [
            np.zeros((4,), dtype=np.float32),  # 1-D
            np.zeros((4, 1), dtype=np.float32),  # mono
            np.zeros((4, 3), dtype=np.float32),  # 3-channel
            np.zeros((2, 2, 2), dtype=np.float32),  # 3-D
        ],
    )
    def test_invalid_shape_raises_value_error(self, bad_frame: np.ndarray):
        sink = RawPcmStdoutSink(stream=io.BytesIO())
        try:
            with pytest.raises(ValueError):
                sink.write(bad_frame)
        finally:
            sink.close()

    @pytest.mark.parametrize(
        "dtype",
        [np.float64, np.int16, np.int32, np.uint8],
    )
    def test_invalid_dtype_raises_value_error(self, dtype: np.dtype):
        sink = RawPcmStdoutSink(stream=io.BytesIO())
        try:
            with pytest.raises(ValueError):
                sink.write(np.zeros((4, CHANNELS), dtype=dtype))
        finally:
            sink.close()


class TestRawPcmStdoutSinkLifecycle:
    def test_write_after_close_raises_runtime_error(self):
        sink = RawPcmStdoutSink(stream=io.BytesIO())
        sink.close()
        with pytest.raises(RuntimeError, match="closed"):
            sink.write(np.zeros((4, CHANNELS), dtype=np.float32))

    def test_close_is_idempotent(self):
        sink = RawPcmStdoutSink(stream=io.BytesIO())
        sink.close()
        # Second close must be a quiet no-op rather than an error.
        sink.close()

    def test_close_flushes_but_does_not_close_stream(self, mocker: MockerFixture):
        buf = io.BytesIO()
        flush_spy = mocker.spy(buf, "flush")
        sink = RawPcmStdoutSink(stream=buf)
        sink.write(np.zeros((4, CHANNELS), dtype=np.float32))
        sink.close()

        flush_spy.assert_called_once()
        # The default stream (sys.stdout.buffer) must outlive the sink;
        # check the BytesIO surrogate stays open.
        assert buf.closed is False

    def test_context_manager_closes_on_exit(self):
        buf = io.BytesIO()
        with RawPcmStdoutSink(stream=buf) as sink:
            sink.write(np.zeros((8, CHANNELS), dtype=np.float32))

        # After the ``with`` block, the sink must reject further
        # writes — demonstrates that ``__exit__`` ran ``close``.
        with pytest.raises(RuntimeError, match="closed"):
            sink.write(np.zeros((4, CHANNELS), dtype=np.float32))

    def test_context_manager_propagates_exception_and_closes(self):
        buf = io.BytesIO()
        sentinel = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            with RawPcmStdoutSink(stream=buf) as sink:
                sink.write(np.zeros((4, CHANNELS), dtype=np.float32))
                raise sentinel

        with pytest.raises(RuntimeError, match="closed"):
            sink.write(np.zeros((4, CHANNELS), dtype=np.float32))


class TestRawPcmStdoutSinkDefaultStream:
    def test_default_stream_is_sys_stdout_buffer(self):
        sink = RawPcmStdoutSink()
        try:
            # The fallback target must be the interpreter's binary
            # stdout so the CLI pipe mode works without explicit
            # wiring.
            assert sink._stream is sys.stdout.buffer  # noqa: SLF001
        finally:
            sink.close()
