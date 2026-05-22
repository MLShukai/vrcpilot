"""PyAV-backed minimal recorders for e2e scenarios (private helper).

These are deliberately small, e2e-local replacements for the sink
classes that lived under ``vrcpilot.capture.sinks`` /
``vrcpilot.speaker`` until the unified ``vrcpilot record`` CLI landed.

Why duplicate the recipe instead of importing from
:mod:`vrcpilot.cli.record.muxer`?

* The muxers under ``vrcpilot.cli.record`` are intentionally CLI
  internals (not part of any public ``__all__``). The e2e suite is
  meant to read like a Python-API user's program; importing the CLI's
  private muxer would couple the scenarios to an internal contract
  that may change without notice.
* The e2e flavour can be much smaller — single-stream, no thread lock
  (CaptureLoop / SpeakerLoop only call the callback from the worker
  thread, never concurrently with anything else here), no mid-stream
  size validation. The scenarios just need "open, append N frames,
  close" semantics.

Both classes follow the same shape as
:mod:`vrcpilot.cli.record.muxer.Mp4FileMuxer` /
:mod:`vrcpilot.cli.record.muxer.WavFileMuxer`: open a PyAV
:class:`av.container.OutputContainer`, add one stream, encode frames
on demand, drain on close. They double as worked examples of
"compose your own PyAV writer around CaptureLoop / SpeakerLoop".
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from types import TracebackType
from typing import Self

import av
import av.audio.stream
import av.container
import av.video.stream
import numpy as np
from numpy.typing import NDArray

#: Pixel format passed to the H.264 encoder. ``yuv420p`` is the most
#: widely decodable subset and what every reasonable web/desktop
#: player expects.
_VIDEO_PIX_FMT: str = "yuv420p"

#: Sample rate the speaker backend produces. Mirrors
#: :data:`vrcpilot.speaker.base.SAMPLE_RATE` without importing from the
#: package's private modules.
_SAMPLE_RATE: int = 48000

#: Channel count the speaker backend produces. Mirrors
#: :data:`vrcpilot.speaker.base.CHANNELS`.
_CHANNELS: int = 2

#: Packed signed 16-bit format used by the ``pcm_s16le`` encoder.
_AUDIO_FORMAT_S16: str = "s16"

#: Stereo layout name accepted by :func:`av.AudioFrame.from_ndarray`.
_AUDIO_LAYOUT_STEREO: str = "stereo"

#: Symmetric quantisation scale (``+32767``) used when converting
#: float32 chunks to 16-bit PCM. Matches the behaviour of
#: :func:`vrcpilot.cli.record.muxer._float32_to_int16` so artifacts
#: written via this helper sound identical to those written by the
#: CLI.
_INT16_SCALE: float = float(np.iinfo(np.int16).max)


def _fps_to_fraction(fps: float) -> Fraction:
    """Normalise ``fps`` to a rational with denominator up to 1000."""
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    return Fraction(fps).limit_denominator(1000)


class Mp4VideoRecorder:
    """Video-only MP4 recorder (libx264 + yuv420p), e2e local.

    Mirrors the construction recipe of
    :class:`vrcpilot.cli.record.muxer.Mp4FileMuxer` but trimmed to a
    single video stream and no thread lock — CaptureLoop only invokes
    the callback from its single worker thread.

    Args:
        path: Destination ``.mp4`` path. Parent directory must already
            exist.
        fps: Playback frame rate stored in the mp4 container.

    Raises:
        ValueError: ``fps <= 0``.
    """

    _path: Path
    _container: av.container.OutputContainer
    _stream: av.video.stream.VideoStream
    _video_size: tuple[int, int] | None
    _frame_count: int
    _closed: bool

    def __init__(self, path: Path, fps: float) -> None:
        fps_frac = _fps_to_fraction(fps)
        self._path = path
        self._container = av.open(str(path), mode="w", format="mp4")
        # add_stream's overload set includes **kwargs so pyright sees it
        # as partially unknown; the Literal-keyed overload is the one
        # being picked and returns ``VideoStream``.
        stream: av.video.stream.VideoStream = self._container.add_stream(  # pyright: ignore[reportUnknownMemberType]
            "libx264", rate=fps_frac
        )
        stream.pix_fmt = _VIDEO_PIX_FMT
        stream.time_base = Fraction(fps_frac.denominator, fps_frac.numerator)
        stream.codec_context.framerate = fps_frac
        self._stream = stream
        self._video_size = None
        self._frame_count = 0
        self._closed = False

    @property
    def frame_count(self) -> int:
        """Number of frames encoded so far."""
        return self._frame_count

    def write(self, frame_rgb: NDArray[np.uint8]) -> None:
        """Append one ``(H, W, 3)`` uint8 RGB frame."""
        if self._closed:
            raise RuntimeError("Mp4VideoRecorder is closed")
        if frame_rgb.ndim != 3 or frame_rgb.shape[2] != 3:
            raise ValueError(
                f"video frame must have shape (H, W, 3), got {frame_rgb.shape}"
            )
        if frame_rgb.dtype != np.uint8:
            raise ValueError(f"video frame must be uint8, got {frame_rgb.dtype}")

        h, w = int(frame_rgb.shape[0]), int(frame_rgb.shape[1])
        if self._video_size is None:
            self._stream.width = w
            self._stream.height = h
            self._video_size = (w, h)
        elif (w, h) != self._video_size:
            locked_w, locked_h = self._video_size
            raise ValueError(
                "frame size changed mid-stream: "
                f"locked=({locked_w}, {locked_h}), got=({w}, {h})"
            )

        frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24").reformat(
            format=_VIDEO_PIX_FMT
        )
        frame.pts = self._frame_count
        for packet in self._stream.encode(frame):
            self._container.mux(packet)
        self._frame_count += 1

    def close(self) -> None:
        """Flush encoder and close the container.

        Idempotent.
        """
        if self._closed:
            return
        self._closed = True
        for packet in self._stream.encode(None):
            self._container.mux(packet)
        self._container.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()


class WavAudioRecorder:
    """Audio-only WAV recorder (pcm_s16le / 48 kHz / stereo), e2e local.

    Mirrors :class:`vrcpilot.cli.record.muxer.WavFileMuxer`. Input is
    the speaker backend's ``(N, CHANNELS) float32`` chunk; samples are
    scaled by ``+32767`` and clipped before being cast to ``int16``
    (saturation, not wrap-around).

    Args:
        path: Destination ``.wav`` path. Parent directory must already
            exist.
    """

    _path: Path
    _container: av.container.OutputContainer
    _stream: av.audio.stream.AudioStream
    _sample_count: int
    _closed: bool

    def __init__(self, path: Path) -> None:
        self._path = path
        self._container = av.open(str(path), mode="w", format="wav")
        stream: av.audio.stream.AudioStream = self._container.add_stream(  # pyright: ignore[reportUnknownMemberType]
            "pcm_s16le", rate=_SAMPLE_RATE
        )
        stream.format = _AUDIO_FORMAT_S16
        stream.layout = _AUDIO_LAYOUT_STEREO
        stream.time_base = Fraction(1, _SAMPLE_RATE)
        self._stream = stream
        self._sample_count = 0
        self._closed = False

    @property
    def sample_count(self) -> int:
        """Number of interleaved audio samples encoded so far."""
        return self._sample_count

    def write(self, chunk_pcm: NDArray[np.float32]) -> None:
        """Append one ``(N, CHANNELS)`` float32 PCM chunk."""
        if self._closed:
            raise RuntimeError("WavAudioRecorder is closed")
        if chunk_pcm.ndim != 2 or chunk_pcm.shape[1] != _CHANNELS:
            raise ValueError(
                f"audio chunk must have shape (N, {_CHANNELS}), "
                f"got {chunk_pcm.shape}"
            )
        if chunk_pcm.dtype != np.float32:
            raise ValueError(f"audio chunk must be float32, got {chunk_pcm.dtype}")

        n = int(chunk_pcm.shape[0])
        if n == 0:
            return

        info = np.iinfo(np.int16)
        scaled = chunk_pcm * _INT16_SCALE
        clipped = np.clip(scaled, info.min, info.max)
        int16 = clipped.astype(np.int16)
        # pcm_s16le expects packed (interleaved) int16 samples arranged
        # as a single ``(1, N * CHANNELS)`` row.
        packed: NDArray[np.int16] = int16.reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(
            packed, format=_AUDIO_FORMAT_S16, layout=_AUDIO_LAYOUT_STEREO
        )
        frame.sample_rate = _SAMPLE_RATE
        frame.pts = self._sample_count
        for packet in self._stream.encode(frame):
            self._container.mux(packet)
        self._sample_count += n

    def close(self) -> None:
        """Flush encoder and close the container.

        Idempotent.
        """
        if self._closed:
            return
        self._closed = True
        for packet in self._stream.encode(None):
            self._container.mux(packet)
        self._container.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()
