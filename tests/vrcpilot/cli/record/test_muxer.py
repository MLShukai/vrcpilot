"""Tests for :mod:`vrcpilot.cli.record.muxer`."""

from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import av
import numpy as np
import pytest
from numpy.typing import NDArray

from vrcpilot.cli.record.muxer import (
    BaseMuxer,
    MkvStdoutMuxer,
    Mp4FileMuxer,
    WavFileMuxer,
)


def _video_frame(
    *, height: int = 48, width: int = 64, fill: int = 0
) -> NDArray[np.uint8]:
    """Build a deterministic ``(H, W, 3) uint8`` RGB frame for tests."""
    return np.full((height, width, 3), fill, dtype=np.uint8)


def _audio_chunk(*, n: int = 1024) -> NDArray[np.float32]:
    """Build a small float32 stereo audio chunk in the ``[-1, 1]`` band."""
    rng = np.random.default_rng(seed=42)
    return (rng.standard_normal((n, 2)).astype(np.float32) * 0.1).astype(np.float32)


# ---------------------------------------------------------------------------
# BaseMuxer
# ---------------------------------------------------------------------------


class TestBaseMuxer:
    def test_cannot_instantiate_abstract_base(self) -> None:
        with pytest.raises(TypeError):
            BaseMuxer()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Mp4FileMuxer
# ---------------------------------------------------------------------------


class TestMp4FileMuxer:
    def test_video_only_writes_one_video_stream(self, tmp_path: Path) -> None:
        out = tmp_path / "video.mp4"
        with Mp4FileMuxer(out, fps=30.0, video=True, audio=False) as muxer:
            for _ in range(5):
                muxer.write_video(_video_frame())
            assert muxer.frame_count == 5
            assert muxer.sample_count == 0

        container = av.open(str(out), mode="r")
        try:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 0
            vstream = container.streams.video[0]
            assert vstream.width == 64
            assert vstream.height == 48
        finally:
            container.close()

    def test_video_plus_audio_writes_two_streams(self, tmp_path: Path) -> None:
        out = tmp_path / "av.mp4"
        with Mp4FileMuxer(out, fps=30.0, video=True, audio=True) as muxer:
            for _ in range(3):
                muxer.write_video(_video_frame())
            # 48000 samples = exactly 1 second of stereo audio.
            muxer.write_audio(np.zeros((48000, 2), dtype=np.float32))
            assert muxer.frame_count == 3
            assert muxer.sample_count == 48000

        container = av.open(str(out), mode="r")
        try:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 1
        finally:
            container.close()

    def test_audio_only_mp4_writes_one_audio_stream(self, tmp_path: Path) -> None:
        out = tmp_path / "audio.mp4"
        with Mp4FileMuxer(out, fps=30.0, video=False, audio=True) as muxer:
            muxer.write_audio(_audio_chunk(n=4096))

        container = av.open(str(out), mode="r")
        try:
            assert len(container.streams.video) == 0
            assert len(container.streams.audio) == 1
        finally:
            container.close()

    def test_video_false_audio_false_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="at least one of video or audio"):
            Mp4FileMuxer(tmp_path / "x.mp4", fps=30.0, video=False, audio=False)

    @pytest.mark.parametrize("fps", [0.0, -1.0, -30.0])
    def test_nonpositive_fps_raises(self, tmp_path: Path, fps: float) -> None:
        with pytest.raises(ValueError, match="fps must be positive"):
            Mp4FileMuxer(tmp_path / "x.mp4", fps=fps, video=True, audio=False)

    def test_video_frame_dtype_must_be_uint8(self, tmp_path: Path) -> None:
        muxer = Mp4FileMuxer(tmp_path / "v.mp4", fps=30.0, video=True, audio=False)
        try:
            bad = np.zeros((48, 64, 3), dtype=np.float32)
            with pytest.raises(ValueError, match="uint8"):
                muxer.write_video(bad)  # type: ignore[arg-type]
        finally:
            muxer.close()

    @pytest.mark.parametrize(
        "shape",
        [
            (48, 64),  # missing channel axis
            (48, 64, 4),  # RGBA, not RGB
            (3, 48, 64),  # planar
        ],
    )
    def test_video_frame_shape_must_be_hxwx3(
        self, tmp_path: Path, shape: tuple[int, ...]
    ) -> None:
        muxer = Mp4FileMuxer(tmp_path / "v.mp4", fps=30.0, video=True, audio=False)
        try:
            bad = np.zeros(shape, dtype=np.uint8)
            with pytest.raises(ValueError, match="shape"):
                muxer.write_video(bad)
        finally:
            muxer.close()

    def test_video_frame_size_change_mid_stream_raises(self, tmp_path: Path) -> None:
        muxer = Mp4FileMuxer(tmp_path / "v.mp4", fps=30.0, video=True, audio=False)
        try:
            muxer.write_video(_video_frame(height=48, width=64))
            with pytest.raises(ValueError, match="frame size changed mid-stream"):
                muxer.write_video(_video_frame(height=72, width=128))
        finally:
            muxer.close()

    def test_audio_chunk_dtype_must_be_float32(self, tmp_path: Path) -> None:
        muxer = Mp4FileMuxer(tmp_path / "a.mp4", fps=30.0, video=False, audio=True)
        try:
            bad = np.zeros((1024, 2), dtype=np.int16)
            with pytest.raises(ValueError, match="float32"):
                muxer.write_audio(bad)  # type: ignore[arg-type]
        finally:
            muxer.close()

    @pytest.mark.parametrize(
        "shape",
        [
            (1024,),  # 1-D, missing channel axis
            (1024, 1),  # mono — wrong channel count
            (1024, 3),  # surround — wrong channel count
        ],
    )
    def test_audio_chunk_shape_must_be_n_by_channels(
        self, tmp_path: Path, shape: tuple[int, ...]
    ) -> None:
        muxer = Mp4FileMuxer(tmp_path / "a.mp4", fps=30.0, video=False, audio=True)
        try:
            bad = np.zeros(shape, dtype=np.float32)
            with pytest.raises(ValueError, match="shape"):
                muxer.write_audio(bad)
        finally:
            muxer.close()

    def test_context_manager_closes_on_exit(self, tmp_path: Path) -> None:
        out = tmp_path / "ctx.mp4"
        with Mp4FileMuxer(out, fps=30.0, video=True, audio=False) as muxer:
            muxer.write_video(_video_frame())
        # After __exit__, calling write_video must fail with the closed
        # check (cheap way to confirm close() ran).
        with pytest.raises(RuntimeError, match="closed"):
            muxer.write_video(_video_frame())

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        muxer = Mp4FileMuxer(tmp_path / "idem.mp4", fps=30.0, video=True, audio=False)
        muxer.write_video(_video_frame())
        muxer.close()
        # Second call must be a no-op rather than raising.
        muxer.close()

    def test_write_video_when_video_false_raises(self, tmp_path: Path) -> None:
        muxer = Mp4FileMuxer(tmp_path / "noa.mp4", fps=30.0, video=False, audio=True)
        try:
            with pytest.raises(RuntimeError, match="video=False"):
                muxer.write_video(_video_frame())
        finally:
            muxer.close()

    def test_write_audio_when_audio_false_raises(self, tmp_path: Path) -> None:
        muxer = Mp4FileMuxer(tmp_path / "nov.mp4", fps=30.0, video=True, audio=False)
        try:
            with pytest.raises(RuntimeError, match="audio=False"):
                muxer.write_audio(_audio_chunk())
        finally:
            muxer.close()


# ---------------------------------------------------------------------------
# WavFileMuxer
# ---------------------------------------------------------------------------


class TestWavFileMuxer:
    def test_writes_48k_stereo_s16_wav(self, tmp_path: Path) -> None:
        out = tmp_path / "audio.wav"
        with WavFileMuxer(out) as muxer:
            muxer.write_audio(np.zeros((48000, 2), dtype=np.float32))
            assert muxer.sample_count == 48000

        with wave.open(str(out), "rb") as w:
            assert w.getnchannels() == 2
            assert w.getframerate() == 48000
            assert w.getsampwidth() == 2
            assert w.getnframes() == 48000

    def test_write_video_always_raises(self, tmp_path: Path) -> None:
        muxer = WavFileMuxer(tmp_path / "v.wav")
        try:
            with pytest.raises(RuntimeError, match="does not accept video"):
                muxer.write_video(_video_frame())
        finally:
            muxer.close()

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        muxer = WavFileMuxer(tmp_path / "i.wav")
        muxer.write_audio(_audio_chunk())
        muxer.close()
        muxer.close()

    def test_frame_count_is_always_zero(self, tmp_path: Path) -> None:
        with WavFileMuxer(tmp_path / "fc.wav") as muxer:
            muxer.write_audio(_audio_chunk())
            assert muxer.frame_count == 0

    def test_empty_chunk_is_noop(self, tmp_path: Path) -> None:
        with WavFileMuxer(tmp_path / "empty.wav") as muxer:
            muxer.write_audio(np.zeros((0, 2), dtype=np.float32))
            assert muxer.sample_count == 0

    def test_audio_validation_rejects_bad_input(self, tmp_path: Path) -> None:
        muxer = WavFileMuxer(tmp_path / "bad.wav")
        try:
            with pytest.raises(ValueError, match="shape"):
                muxer.write_audio(np.zeros((1024,), dtype=np.float32))
            with pytest.raises(ValueError, match="float32"):
                muxer.write_audio(np.zeros((1024, 2), dtype=np.int16))  # type: ignore[arg-type]
        finally:
            muxer.close()


# ---------------------------------------------------------------------------
# MkvStdoutMuxer
# ---------------------------------------------------------------------------


# EBML / Matroska start marker, expected at byte offset 0 of every mkv
# file. See https://www.matroska.org/technical/elements.html.
_MKV_MAGIC = bytes.fromhex("1A45DFA3")


class _NonCloseableBytesIO(io.BytesIO):
    """A :class:`BytesIO` that records whether ``close`` was called.

    Used to assert that :class:`MkvStdoutMuxer` does **not** close
    a stream we hand it — the caller owns the lifecycle of any
    stream they passed in via ``stream=``.
    """

    closed_by_muxer: bool = False

    def close(self) -> None:  # pragma: no cover - asserted via flag
        self.closed_by_muxer = True
        super().close()


class TestMkvStdoutMuxer:
    def test_av_combination_emits_mkv_magic_to_stream(self) -> None:
        buf = io.BytesIO()
        with MkvStdoutMuxer(fps=30.0, video=True, audio=True, stream=buf) as muxer:
            for _ in range(3):
                muxer.write_video(_video_frame())
            muxer.write_audio(_audio_chunk(n=2048))
            assert muxer.frame_count == 3
            assert muxer.sample_count == 2048

        data = buf.getvalue()
        assert data[:4] == _MKV_MAGIC
        # Re-open as a Matroska container and verify both streams are
        # present.
        container = av.open(io.BytesIO(data), mode="r")
        try:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 1
        finally:
            container.close()

    def test_video_only_mkv(self) -> None:
        buf = io.BytesIO()
        with MkvStdoutMuxer(fps=30.0, video=True, audio=False, stream=buf) as muxer:
            muxer.write_video(_video_frame())

        container = av.open(io.BytesIO(buf.getvalue()), mode="r")
        try:
            assert len(container.streams.video) == 1
            assert len(container.streams.audio) == 0
        finally:
            container.close()

    def test_audio_only_mkv(self) -> None:
        buf = io.BytesIO()
        with MkvStdoutMuxer(fps=30.0, video=False, audio=True, stream=buf) as muxer:
            muxer.write_audio(_audio_chunk(n=2048))

        container = av.open(io.BytesIO(buf.getvalue()), mode="r")
        try:
            assert len(container.streams.video) == 0
            assert len(container.streams.audio) == 1
        finally:
            container.close()

    def test_default_stream_is_sys_stdout_buffer(self) -> None:
        # ``sys.stdout.buffer`` is a readonly descriptor on the live
        # stdout object so we can't swap it via mocker. Instead, build
        # the muxer with no ``stream`` kwarg, inspect the private
        # ``_stream`` slot for identity with the interpreter's binary
        # stdout, then close without ever writing — so we do not
        # actually emit mkv bytes to the test runner's stdout.
        muxer = MkvStdoutMuxer(fps=30.0, video=True, audio=False)
        try:
            assert muxer._stream is sys.stdout.buffer  # noqa: SLF001
        finally:
            muxer.close()

    def test_video_false_audio_false_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one of video or audio"):
            MkvStdoutMuxer(fps=30.0, video=False, audio=False)

    @pytest.mark.parametrize("fps", [0.0, -1.0])
    def test_nonpositive_fps_raises(self, fps: float) -> None:
        with pytest.raises(ValueError, match="fps must be positive"):
            MkvStdoutMuxer(fps=fps, video=True, audio=False)

    def test_stream_is_not_closed_by_muxer(self) -> None:
        buf = _NonCloseableBytesIO()
        with MkvStdoutMuxer(fps=30.0, video=True, audio=False, stream=buf) as muxer:
            muxer.write_video(_video_frame())

        # The muxer must only flush, never close, a caller-owned stream
        # (the caller passed it in, so they own the lifecycle).
        assert buf.closed_by_muxer is False
        assert not buf.closed

    def test_close_is_idempotent(self) -> None:
        muxer = MkvStdoutMuxer(fps=30.0, video=True, audio=False, stream=io.BytesIO())
        muxer.write_video(_video_frame())
        muxer.close()
        muxer.close()

    def test_video_frame_size_change_mid_stream_raises(self) -> None:
        muxer = MkvStdoutMuxer(fps=30.0, video=True, audio=False, stream=io.BytesIO())
        try:
            muxer.write_video(_video_frame(height=48, width=64))
            with pytest.raises(ValueError, match="frame size changed mid-stream"):
                muxer.write_video(_video_frame(height=96, width=128))
        finally:
            muxer.close()
