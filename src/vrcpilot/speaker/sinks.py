"""Audio sinks for the speaker modality.

:class:`WavFileSink` persists a :class:`SpeakerBackend` float32 PCM
stream to a 16-bit RIFF/WAV file using the same closed-state /
context-manager lifecycle as :class:`vrcpilot.capture.sinks.Mp4FrameSink`.

:class:`RawPcmStdoutSink` is the headerless counterpart for the CLI
``vrcpilot record`` pipe mode: it emits the same ``int16`` PCM payload
straight to a binary stream (``sys.stdout.buffer`` by default) so
downstream tools like ``ffmpeg`` can re-encode without an intermediate
file.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self

import numpy as np
from numpy.typing import NDArray

from vrcpilot.speaker.base import CHANNELS, SAMPLE_RATE

#: Bytes per audio sample (per channel) in the written WAV file.
#: 16-bit signed PCM is hard-coded; the constructor does not expose it.
_SAMPLE_WIDTH_BYTES = 2

#: Quantisation scale for ``float32 -> int16`` conversion. Using
#: ``int16.max`` (``32767``) keeps the mapping symmetric around zero;
#: see :func:`_float32_to_int16` for the full clipping rationale.
_INT16_SCALE: float = float(np.iinfo(np.int16).max)


def _validate_float32_frame(frame: NDArray[np.float32], *, sink_name: str) -> None:
    """Raise :class:`ValueError` unless ``frame`` is ``(N, CHANNELS) float32``.

    Shared by every sink that consumes the speaker backend's
    ``float32`` chunk contract so the wording of the error stays
    consistent across :class:`WavFileSink` /
    :class:`RawPcmStdoutSink`.

    Args:
        frame: Candidate audio chunk.
        sink_name: Prefixed into the error message so the failing
            sink class is obvious to the caller.

    Raises:
        ValueError: ``frame.dtype`` is not :class:`numpy.float32`, or
            its shape is not ``(N, CHANNELS)``.
    """
    if frame.dtype != np.float32:
        raise ValueError(f"{sink_name} expects float32 frames, got dtype={frame.dtype}")
    if frame.ndim != 2 or frame.shape[1] != CHANNELS:
        raise ValueError(
            f"{sink_name} expects frames of shape (N, "
            f"{CHANNELS}), got shape={frame.shape}"
        )


def _float32_to_int16(frame: NDArray[np.float32]) -> NDArray[np.int16]:
    """Quantise an ``(N, CHANNELS)`` float32 buffer to ``int16``.

    Multiplies by :data:`_INT16_SCALE` (``+32767``) so the mapping is
    symmetric around zero (``+1.0 -> +32767``, ``-1.0 -> -32767``),
    then clips to the full ``[-32768, 32767]`` int16 band before
    casting so out-of-range samples saturate to the int16 extremes
    rather than wrapping (a value outside ``[-1.0, 1.0]`` does not
    silently corrupt the output).
    """
    scaled = frame * _INT16_SCALE
    info = np.iinfo(np.int16)
    clipped = np.clip(scaled, info.min, info.max)
    return clipped.astype(np.int16)


class WavFileSink:
    """Stream ``float32`` PCM frames to a 16-bit signed WAV file.

    :meth:`write` accepts the ``(N, CHANNELS)`` float32 layout the
    speaker backends produce; out-of-range samples are clamped to the
    int16 range before quantisation so overdriven input clips rather
    than wraps. Output format is fixed at 48 kHz stereo, signed 16-bit
    little-endian PCM (mirroring the backend contract — not
    configurable).

    The constructor opens the underlying :mod:`wave` writer immediately,
    so the parent directory must already exist; otherwise
    :class:`FileNotFoundError` propagates. :meth:`close` is idempotent.
    """

    _output_path: Path
    _writer: wave.Wave_write | None
    _sample_count: int
    _closed: bool

    def __init__(self, output_path: Path) -> None:
        self._output_path = output_path
        writer = wave.open(str(output_path), "wb")
        writer.setnchannels(CHANNELS)
        writer.setsampwidth(_SAMPLE_WIDTH_BYTES)
        writer.setframerate(SAMPLE_RATE)
        self._writer = writer
        self._sample_count = 0
        self._closed = False

    @property
    def sample_count(self) -> int:
        """Total number of interleaved samples written so far.

        One ``sample`` counts a full ``CHANNELS``-wide frame, matching
        ``wave.Wave_read.getnframes`` semantics.
        """
        return self._sample_count

    def write(self, frame: NDArray[np.float32]) -> None:
        """Append a chunk of audio to the WAV file.

        Args:
            frame: ``(N, CHANNELS)`` float32 ndarray; ``N == 0`` is a
                no-op so backends are free to forward empty reads.

        Raises:
            RuntimeError: The sink has already been closed.
            ValueError: ``frame`` does not have shape
                ``(N, CHANNELS)`` or its dtype is not ``np.float32``.
        """
        if self._closed:
            raise RuntimeError("WavFileSink is closed")

        _validate_float32_frame(frame, sink_name="WavFileSink")

        n = frame.shape[0]
        if n == 0:
            return

        int16 = _float32_to_int16(frame)

        # ``writeframesraw`` lets the header size be patched by
        # ``close()`` once the total payload length is known.
        assert self._writer is not None  # _closed guards otherwise
        self._writer.writeframesraw(int16.tobytes())
        self._sample_count += n

    def close(self) -> None:
        """Finalise the WAV header and release the underlying writer.

        Idempotent: calling twice is a no-op rather than an error so
        the context-manager exit path is safe even when the user has
        already closed explicitly.
        """
        if self._closed:
            return
        self._closed = True
        writer = self._writer
        self._writer = None
        if writer is not None:
            writer.close()

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


class RawPcmStdoutSink:
    """Stream ``float32`` PCM frames as headerless ``s16le`` to a binary
    stream.

    Designed for the CLI ``vrcpilot record`` command's pipe mode: when
    the user omits ``-o``, the recording is emitted as raw signed 16-bit
    little-endian PCM (48 kHz, stereo, interleaved) directly to the
    stream so downstream tools (``ffmpeg`` etc.) can pick up the audio
    without an intermediate file.

    The stream is **not self-describing** — there is no header. Consumers
    must specify the format explicitly, e.g.::

        ffmpeg -f s16le -ar 48000 -ac 2 -i - ...

    :meth:`write` shares the ``(N, CHANNELS) float32`` contract with
    :class:`WavFileSink`; the same quantisation is applied so the byte
    stream matches what would have been written to a WAV file (sans
    RIFF header).

    Args:
        stream: Destination binary stream. Defaults to
            ``sys.stdout.buffer`` so the CLI's stdout pipe works without
            explicit wiring; tests inject :class:`io.BytesIO`.

    The stream is **never** closed by this sink — :meth:`close` only
    flushes — because the default target (``sys.stdout``) is owned by
    the interpreter and must outlive the sink for the surrounding
    process to finish cleanly.
    """

    _stream: BinaryIO
    _sample_count: int
    _closed: bool

    def __init__(self, *, stream: BinaryIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout.buffer
        self._sample_count = 0
        self._closed = False

    @property
    def sample_count(self) -> int:
        """Total number of interleaved samples written so far.

        One ``sample`` counts a full ``CHANNELS``-wide frame, matching
        :attr:`WavFileSink.sample_count` semantics.
        """
        return self._sample_count

    def write(self, frame: NDArray[np.float32]) -> None:
        """Append a chunk of audio to the stream as ``s16le`` bytes.

        Args:
            frame: ``(N, CHANNELS)`` float32 ndarray; ``N == 0`` is a
                no-op so backends are free to forward empty reads.

        Raises:
            RuntimeError: The sink has already been closed.
            ValueError: ``frame`` does not have shape
                ``(N, CHANNELS)`` or its dtype is not ``np.float32``.
        """
        if self._closed:
            raise RuntimeError("RawPcmStdoutSink is closed")

        _validate_float32_frame(frame, sink_name="RawPcmStdoutSink")

        n = frame.shape[0]
        if n == 0:
            return

        int16 = _float32_to_int16(frame)
        # ``<i2`` (little-endian int16) is explicit so the byte stream
        # stays s16le even on a hypothetical big-endian host. ``copy=
        # False`` avoids a redundant buffer copy when the source array
        # is already native-endian little-endian (the common case on
        # x86_64).
        self._stream.write(int16.astype("<i2", copy=False).tobytes())
        self._sample_count += n

    def close(self) -> None:
        """Flush the underlying stream; idempotent and never closes it.

        The default stream is ``sys.stdout.buffer``, which is owned by
        the interpreter — closing it would break anything written
        afterwards (e.g. an ``atexit`` log line). Tests pass their own
        :class:`io.BytesIO` and check it stays open.
        """
        if self._closed:
            return
        self._closed = True
        self._stream.flush()

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
