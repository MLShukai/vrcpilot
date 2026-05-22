"""PyAV-backed muxers used internally by the ``vrcpilot record`` command.

Three concrete classes share :class:`BaseMuxer`:

- :class:`Mp4FileMuxer` — H.264 (libx264 / yuv420p) video and AAC
  (fltp) audio in an ``.mp4`` container. Either or both streams may be
  enabled at construction time.
- :class:`WavFileMuxer` — audio-only, ``pcm_s16le`` 48 kHz stereo in a
  RIFF/WAV container. Video writes are rejected at runtime.
- :class:`MkvStdoutMuxer` — same codecs as :class:`Mp4FileMuxer` but
  packed into a non-seekable Matroska byte stream targeted at a
  :class:`typing.BinaryIO` (defaults to ``sys.stdout.buffer``) so the
  CLI can pipe a self-describing recording to downstream tools.

This module is **CLI-internal**: it is intentionally absent from
``__all__`` and not re-exported via :mod:`vrcpilot.cli.record`'s public
surface. Stable users compose :class:`vrcpilot.CaptureLoop` /
:class:`vrcpilot.SpeakerLoop` with their own writers.
"""

import abc
import sys
import threading
from fractions import Fraction
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self, override

import av
import av.audio.stream
import av.container
import av.video.stream
import numpy as np
from numpy.typing import NDArray

from vrcpilot.speaker.base import CHANNELS, SAMPLE_RATE

#: Pixel format passed to the H.264 encoder. yuv420p is the most
#: widely-decodable subset and what every reasonable web/desktop
#: player expects.
_VIDEO_PIX_FMT = "yuv420p"

#: Planar float32 audio format used to drive the AAC encoder; PyAV's
#: ``aac`` encoder requires planar input regardless of the source
#: layout, so we always reformat to ``fltp`` before encoding.
_AUDIO_FORMAT_FLTP = "fltp"

#: Packed signed 16-bit format used by the ``pcm_s16le`` encoder that
#: backs :class:`WavFileMuxer`.
_AUDIO_FORMAT_S16 = "s16"

#: Stereo layout name accepted by :func:`av.AudioFrame.from_ndarray`.
_AUDIO_LAYOUT_STEREO = "stereo"

#: Symmetric quantisation scale matching
#: :mod:`vrcpilot.speaker.sinks` so the produced ``.wav`` bytes are
#: bit-identical to the speaker-only :class:`vrcpilot.WavFileSink` for
#: the same float32 input.
_INT16_SCALE: float = float(np.iinfo(np.int16).max)


def _validate_video_frame(frame: NDArray[np.uint8]) -> None:
    """Enforce the ``(H, W, 3) uint8`` RGB contract shared by all muxers."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(
            f"video frame must have shape (H, W, 3), got shape={frame.shape}"
        )
    if frame.dtype != np.uint8:
        raise ValueError(f"video frame must be uint8, got dtype={frame.dtype}")


def _validate_audio_chunk(chunk: NDArray[np.float32]) -> None:
    """Enforce the speaker backend's ``(N, CHANNELS) float32`` chunk
    contract."""
    if chunk.ndim != 2 or chunk.shape[1] != CHANNELS:
        raise ValueError(
            f"audio chunk must have shape (N, {CHANNELS}), got shape={chunk.shape}"
        )
    if chunk.dtype != np.float32:
        raise ValueError(f"audio chunk must be float32, got dtype={chunk.dtype}")


def _float32_to_int16(chunk: NDArray[np.float32]) -> NDArray[np.int16]:
    """Quantise an ``(N, CHANNELS)`` float32 buffer to ``int16``.

    Multiplies by :data:`_INT16_SCALE` (``+32767``) so the mapping is
    symmetric around zero, then clips before casting so out-of-range
    samples saturate to the int16 extremes rather than wrapping.
    """
    scaled = chunk * _INT16_SCALE
    info = np.iinfo(np.int16)
    clipped = np.clip(scaled, info.min, info.max)
    return clipped.astype(np.int16)


def _fps_to_fraction(fps: float) -> Fraction:
    """Normalise ``fps`` to a rational with denominator up to 1000.

    PyAV's H.264 encoder expects an integer-friendly rate; we mirror
    :class:`vrcpilot.capture.sinks.Y4mStdoutFrameSink`'s convention of
    capping the denominator at 1000 so integer rates stay integers and
    common rationals (29.97 → 2997/100) survive intact.
    """
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    return Fraction(fps).limit_denominator(1000)


class BaseMuxer(abc.ABC):
    """Abstract PyAV-backed muxer accepting RGB video and float32 audio chunks.

    Concrete subclasses own one :class:`av.container.OutputContainer`
    plus zero or more streams. The base class owns the public surface
    (validation, properties, context-manager protocol) so subclasses
    only override the three abstract write/close primitives.

    The class is CLI-internal and **not** part of
    :mod:`vrcpilot.cli.record`'s ``__all__`` — recordings produced by
    library users should compose the public sinks under
    :mod:`vrcpilot.capture.sinks` / :mod:`vrcpilot.speaker.sinks`
    instead.
    """

    @abc.abstractmethod
    def write_video(self, frame_rgb: NDArray[np.uint8]) -> None:
        """Append a single ``(H, W, 3)`` uint8 RGB frame."""
        raise NotImplementedError

    @abc.abstractmethod
    def write_audio(self, chunk_pcm: NDArray[np.float32]) -> None:
        """Append a single ``(N, CHANNELS)`` float32 PCM chunk."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def frame_count(self) -> int:
        """Number of video frames encoded so far."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def sample_count(self) -> int:
        """Number of interleaved audio samples encoded so far."""
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """Flush any pending packets and release the underlying container."""
        raise NotImplementedError

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


def _check_at_least_one_stream(*, video: bool, audio: bool) -> None:
    """Reject muxers configured with no streams at all."""
    if not video and not audio:
        raise ValueError("at least one of video or audio must be True")


class _VideoMixin:
    """Shared video-encoding helpers for libx264-backed muxers.

    Stored as a small mixin so :class:`Mp4FileMuxer` and
    :class:`MkvStdoutMuxer` share frame validation, size-locking and
    PTS bookkeeping without duplicating bodies.
    """

    _container: av.container.OutputContainer
    _video_stream: av.video.stream.VideoStream | None
    _video_size: tuple[int, int] | None
    _frame_count: int
    _video_fps: Fraction

    def _setup_video_stream(self, fps: Fraction) -> av.video.stream.VideoStream:
        # PyAV's add_stream stubs flag the overload as partially unknown
        # because of the trailing **kwargs; the Literal-keyed overload
        # is still picked and returns ``VideoStream``.
        stream: av.video.stream.VideoStream = self._container.add_stream(  # pyright: ignore[reportUnknownMemberType]
            "libx264", rate=fps
        )
        stream.pix_fmt = _VIDEO_PIX_FMT
        # time_base = seconds per tick = denominator / numerator of fps
        stream.time_base = Fraction(fps.denominator, fps.numerator)
        stream.codec_context.framerate = fps
        self._video_fps = fps
        return stream

    def _encode_video(self, frame_rgb: NDArray[np.uint8]) -> None:
        _validate_video_frame(frame_rgb)

        stream = self._video_stream
        if stream is None:
            raise RuntimeError("muxer was constructed with video=False")

        h, w = int(frame_rgb.shape[0]), int(frame_rgb.shape[1])
        if self._video_size is None:
            stream.width = w
            stream.height = h
            self._video_size = (w, h)
        else:
            locked_w, locked_h = self._video_size
            if (w, h) != (locked_w, locked_h):
                raise ValueError(
                    "frame size changed mid-stream: "
                    f"locked=({locked_w}, {locked_h}), got=({w}, {h})"
                )

        frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24").reformat(
            format=_VIDEO_PIX_FMT
        )
        frame.pts = self._frame_count
        for packet in stream.encode(frame):
            self._container.mux(packet)
        self._frame_count += 1


class _AudioMixin:
    """Shared AAC-encoding helpers for libx264-backed containers.

    AAC requires planar float input, so we convert the speaker-shaped
    ``(N, CHANNELS)`` interleaved float32 buffer to ``(CHANNELS, N)``
    contiguous planar before handing it to PyAV.
    """

    _container: av.container.OutputContainer
    _audio_stream: av.audio.stream.AudioStream | None
    _sample_count: int

    def _setup_aac_stream(self) -> av.audio.stream.AudioStream:
        stream: av.audio.stream.AudioStream = self._container.add_stream(  # pyright: ignore[reportUnknownMemberType]
            "aac", rate=SAMPLE_RATE
        )
        stream.format = _AUDIO_FORMAT_FLTP
        stream.layout = _AUDIO_LAYOUT_STEREO
        stream.time_base = Fraction(1, SAMPLE_RATE)
        return stream

    def _encode_aac_audio(self, chunk_pcm: NDArray[np.float32]) -> None:
        _validate_audio_chunk(chunk_pcm)

        stream = self._audio_stream
        if stream is None:
            raise RuntimeError("muxer was constructed with audio=False")

        n = int(chunk_pcm.shape[0])
        if n == 0:
            return

        # PyAV's AAC encoder wants planar float input: shape (channels, N).
        planar: NDArray[np.float32] = np.ascontiguousarray(chunk_pcm.T)
        frame = av.AudioFrame.from_ndarray(
            planar, format=_AUDIO_FORMAT_FLTP, layout=_AUDIO_LAYOUT_STEREO
        )
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self._sample_count
        for packet in stream.encode(frame):
            self._container.mux(packet)
        self._sample_count += n


class Mp4FileMuxer(_VideoMixin, _AudioMixin, BaseMuxer):
    """Muxer that writes H.264 + AAC into an ``.mp4`` file.

    Either or both of ``video`` / ``audio`` may be enabled, but at
    least one must be. The first :meth:`write_video` locks the frame
    size; subsequent calls with a different size raise
    :class:`ValueError`.

    Args:
        output_path: Destination ``.mp4`` path. Parent directory must
            exist; otherwise PyAV raises a :class:`OSError`-derived
            exception when opening the container.
        fps: Playback frame rate stored in the mp4 container.
            ``fps <= 0`` raises :class:`ValueError`.
        video: When ``True`` a libx264 (yuv420p) video stream is
            attached and :meth:`write_video` accepts frames.
        audio: When ``True`` an AAC (fltp, 48 kHz stereo) audio stream
            is attached and :meth:`write_audio` accepts chunks.

    Raises:
        ValueError: ``video`` and ``audio`` are both ``False``, or
            ``fps <= 0``.
    """

    _output_path: Path
    _closed: bool
    _lock: threading.Lock

    def __init__(
        self,
        output_path: Path,
        *,
        fps: float,
        video: bool,
        audio: bool,
    ) -> None:
        _check_at_least_one_stream(video=video, audio=audio)
        fps_frac = _fps_to_fraction(fps)

        self._output_path = output_path
        self._container = av.open(str(output_path), mode="w", format="mp4")
        self._video_stream = None
        self._video_size = None
        self._frame_count = 0
        self._audio_stream = None
        self._sample_count = 0
        self._closed = False
        self._lock = threading.Lock()

        if video:
            self._video_stream = self._setup_video_stream(fps_frac)
        if audio:
            self._audio_stream = self._setup_aac_stream()

    @property
    @override
    def frame_count(self) -> int:
        return self._frame_count

    @property
    @override
    def sample_count(self) -> int:
        return self._sample_count

    @override
    def write_video(self, frame_rgb: NDArray[np.uint8]) -> None:
        if self._closed:
            raise RuntimeError("Mp4FileMuxer is closed")
        with self._lock:
            self._encode_video(frame_rgb)

    @override
    def write_audio(self, chunk_pcm: NDArray[np.float32]) -> None:
        if self._closed:
            raise RuntimeError("Mp4FileMuxer is closed")
        with self._lock:
            self._encode_aac_audio(chunk_pcm)

    @override
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._lock:
            _flush_stream(self._container, self._video_stream)
            _flush_stream(self._container, self._audio_stream)
            self._container.close()


class WavFileMuxer(BaseMuxer):
    """Audio-only muxer writing ``pcm_s16le`` 48 kHz stereo to ``.wav``.

    Float32 input is quantised to int16 with the same symmetric scale
    (``×32767`` with clipping) as :class:`vrcpilot.WavFileSink`, so the
    payload bytes match for identical input. Calling
    :meth:`write_video` always raises :class:`RuntimeError` — the WAV
    container has no video stream.

    Args:
        output_path: Destination ``.wav`` path. Parent directory must
            already exist.
    """

    _output_path: Path
    _container: av.container.OutputContainer
    _audio_stream: av.audio.stream.AudioStream
    _sample_count: int
    _closed: bool
    _lock: threading.Lock

    def __init__(self, output_path: Path) -> None:
        self._output_path = output_path
        self._container = av.open(str(output_path), mode="w", format="wav")
        stream: av.audio.stream.AudioStream = self._container.add_stream(  # pyright: ignore[reportUnknownMemberType]
            "pcm_s16le", rate=SAMPLE_RATE
        )
        stream.format = _AUDIO_FORMAT_S16
        stream.layout = _AUDIO_LAYOUT_STEREO
        stream.time_base = Fraction(1, SAMPLE_RATE)
        self._audio_stream = stream
        self._sample_count = 0
        self._closed = False
        self._lock = threading.Lock()

    @property
    @override
    def frame_count(self) -> int:
        return 0

    @property
    @override
    def sample_count(self) -> int:
        return self._sample_count

    @override
    def write_video(self, frame_rgb: NDArray[np.uint8]) -> None:
        del frame_rgb
        raise RuntimeError("WavFileMuxer does not accept video frames")

    @override
    def write_audio(self, chunk_pcm: NDArray[np.float32]) -> None:
        if self._closed:
            raise RuntimeError("WavFileMuxer is closed")
        _validate_audio_chunk(chunk_pcm)
        n = int(chunk_pcm.shape[0])
        if n == 0:
            return

        with self._lock:
            int16 = _float32_to_int16(chunk_pcm)
            # pcm_s16le expects packed (interleaved) int16 samples
            # arranged as a single (1, N * CHANNELS) row.
            packed: NDArray[np.int16] = int16.reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(
                packed, format=_AUDIO_FORMAT_S16, layout=_AUDIO_LAYOUT_STEREO
            )
            frame.sample_rate = SAMPLE_RATE
            frame.pts = self._sample_count
            for packet in self._audio_stream.encode(frame):
                self._container.mux(packet)
            self._sample_count += n

    @override
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._lock:
            _flush_stream(self._container, self._audio_stream)
            self._container.close()


class MkvStdoutMuxer(_VideoMixin, _AudioMixin, BaseMuxer):
    """Muxer that writes H.264 + AAC into a non-seekable Matroska stream.

    Designed for the CLI ``record`` command's pipe mode: when the user
    omits ``-o``, the recording is emitted to a binary stream
    (``sys.stdout.buffer`` by default) so downstream tools can pick up
    both video and audio without an intermediate file. Matroska is
    chosen over MP4 because mp4 requires a seekable output to patch
    the ``moov`` atom at close-time, which a pipe cannot offer.

    The stream is **never** closed by this muxer — :meth:`close` only
    flushes — because the default target (``sys.stdout.buffer``) is
    owned by the interpreter and must outlive the muxer.

    Args:
        fps: Playback frame rate stored in the matroska container.
        video: When ``True`` a libx264 video stream is attached.
        audio: When ``True`` an AAC audio stream is attached.
        stream: Destination binary stream. Defaults to
            ``sys.stdout.buffer`` so the CLI's stdout pipe works
            without explicit wiring; tests inject :class:`io.BytesIO`.

    Raises:
        ValueError: ``video`` and ``audio`` are both ``False``, or
            ``fps <= 0``.
    """

    _stream: BinaryIO
    _closed: bool
    _lock: threading.Lock

    def __init__(
        self,
        *,
        fps: float,
        video: bool,
        audio: bool,
        stream: BinaryIO | None = None,
    ) -> None:
        _check_at_least_one_stream(video=video, audio=audio)
        fps_frac = _fps_to_fraction(fps)

        self._stream = stream if stream is not None else sys.stdout.buffer
        self._container = av.open(self._stream, mode="w", format="matroska")
        self._video_stream = None
        self._video_size = None
        self._frame_count = 0
        self._audio_stream = None
        self._sample_count = 0
        self._closed = False
        self._lock = threading.Lock()

        if video:
            self._video_stream = self._setup_video_stream(fps_frac)
        if audio:
            self._audio_stream = self._setup_aac_stream()

    @property
    @override
    def frame_count(self) -> int:
        return self._frame_count

    @property
    @override
    def sample_count(self) -> int:
        return self._sample_count

    @override
    def write_video(self, frame_rgb: NDArray[np.uint8]) -> None:
        if self._closed:
            raise RuntimeError("MkvStdoutMuxer is closed")
        with self._lock:
            self._encode_video(frame_rgb)

    @override
    def write_audio(self, chunk_pcm: NDArray[np.float32]) -> None:
        if self._closed:
            raise RuntimeError("MkvStdoutMuxer is closed")
        with self._lock:
            self._encode_aac_audio(chunk_pcm)

    @override
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._lock:
            _flush_stream(self._container, self._video_stream)
            _flush_stream(self._container, self._audio_stream)
            self._container.close()
            # We do not own ``self._stream`` (default is
            # ``sys.stdout.buffer``), so only flush — never close.
            self._stream.flush()


def _flush_stream(
    container: av.container.OutputContainer,
    stream: av.video.stream.VideoStream | av.audio.stream.AudioStream | None,
) -> None:
    """Drain the encoder by feeding ``None`` and muxing the trailing
    packets."""
    if stream is None:
        return
    for packet in stream.encode(None):
        container.mux(packet)
