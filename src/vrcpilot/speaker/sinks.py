"""Audio sinks for the speaker modality.

:class:`WavFileSink` persists a :class:`SpeakerBackend` float32 PCM
stream to a 16-bit RIFF/WAV file using the same closed-state /
context-manager lifecycle as :class:`vrcpilot.capture.sinks.Mp4FrameSink`.
"""

from __future__ import annotations

import wave
from pathlib import Path
from types import TracebackType
from typing import Self

import numpy as np
from numpy.typing import NDArray

from vrcpilot.speaker.base import CHANNELS, SAMPLE_RATE

#: Bytes per audio sample (per channel) in the written WAV file.
#: 16-bit signed PCM is hard-coded; the constructor does not expose it.
_SAMPLE_WIDTH_BYTES = 2

#: Quantisation scale for ``float32 -> int16`` conversion. Using
#: ``int16.max`` (``32767``) keeps the mapping symmetric around zero;
#: see :meth:`WavFileSink.write` for the full clipping rationale.
_INT16_SCALE: float = float(np.iinfo(np.int16).max)


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

        if frame.dtype != np.float32:
            raise ValueError(
                f"WavFileSink expects float32 frames, got dtype={frame.dtype}"
            )
        if frame.ndim != 2 or frame.shape[1] != CHANNELS:
            raise ValueError(
                "WavFileSink expects frames of shape (N, "
                f"{CHANNELS}), got shape={frame.shape}"
            )

        n = frame.shape[0]
        if n == 0:
            return

        # Scale to int16 range first, then clip to int16's full
        # ``[-32768, 32767]`` band so overdriven input saturates
        # symmetrically (``+1.0 -> +32767``, ``-1.0 -> -32767``,
        # while ``-1.5`` clamps to ``-32768`` rather than wrapping).
        scaled = frame * _INT16_SCALE
        info = np.iinfo(np.int16)
        clipped = np.clip(scaled, info.min, info.max)
        int16 = clipped.astype(np.int16)

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
