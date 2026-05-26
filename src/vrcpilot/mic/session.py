"""Public :class:`Mic` session bound to a virtual-cable output device.

Callers drive playback cadence with their own loop; the soundcard
player is opened at construction and released on close / ``__exit__``
/ finaliser.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import numpy as np
from numpy.typing import NDArray

from .base import SAMPLE_RATE
from .devices import lookup_speaker, resolve_device_name


def _validate_chunk(chunk: NDArray[np.float32], *, expected_channels: int) -> None:
    """Reject chunks soundcard would silently misinterpret."""
    if chunk.dtype != np.float32:
        raise ValueError(f"chunk dtype must be float32, got {chunk.dtype}")
    if chunk.ndim == 1:
        chunk_channels = 1
    elif chunk.ndim == 2:
        chunk_channels = int(chunk.shape[1])
    else:
        raise ValueError(
            f"chunk must be 1-D (mono) or 2-D (N, C), got ndim={chunk.ndim}"
        )
    if chunk_channels != expected_channels:
        raise ValueError(
            f"chunk channel count {chunk_channels} disagrees with Mic "
            f"channels {expected_channels}"
        )


class Mic:
    """Session bound to a virtual-cable output device.

    Opened at construction, released on :meth:`close` / ``__exit__`` /
    finaliser.

    Args:
        device: Case-insensitive substring of the target output device
            name (so ``"VRCPilot"`` resolves the full ``"VRCPilotMic"``
            sink). ``None`` falls through to ``$VRCPILOT_MIC_DEVICE``
            then :func:`vrcpilot.mic.default_device_name`.
        sample_rate: Hz; must match the consumer or libpulse / WASAPI
            will resample on the hot path (VRChat expects 48000).
        channels: Output channel count baked into the player. Chunks
            handed to :meth:`play` must agree with this value.

    Raises:
        MicDeviceNotFoundError: No output device matches the resolved
            name, or no default is configured for this platform.
        ImportError: ``soundcard`` is not installed.
        OSError: ``soundcard`` cannot dlopen libpulse / WASAPI.
        RuntimeError: libpulse / WASAPI runtime failure on player entry.
        ValueError: ``sample_rate`` or ``channels`` is not positive.
    """

    def __init__(
        self,
        device: str | None = None,
        *,
        sample_rate: int = SAMPLE_RATE,
        channels: int = 1,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be > 0 (got {sample_rate})")
        if channels <= 0:
            raise ValueError(f"channels must be > 0 (got {channels})")
        self._closed: bool = False
        self._player_cm: Any = None
        self._player: Any = None
        self._device_name: str = resolve_device_name(device)
        speaker: Any = lookup_speaker(self._device_name)
        self._device_id: str = str(getattr(speaker, "id", ""))
        self._sample_rate: int = sample_rate
        self._channels: int = channels

        self._player_cm = speaker.player(  # pyright: ignore[reportUnknownMemberType]
            samplerate=sample_rate,
            channels=channels,
        )
        self._player = (
            self._player_cm.__enter__()  # pyright: ignore[reportUnknownMemberType]
        )

    @property
    def device_name(self) -> str:
        """Substring resolved to pick this device."""
        return self._device_name

    @property
    def device_id(self) -> str:
        """``Speaker.id`` of the resolved device.

        PulseAudio sink name on Linux (e.g. ``"VRCPilotMic"``), WASAPI
        device id on Windows -- divergent from :attr:`device_name` for
        the PipeWire null-sink.
        """
        return self._device_id

    @property
    def sample_rate(self) -> int:
        """Sample rate in Hz baked into the underlying player."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Channel count baked into the underlying player."""
        return self._channels

    def play(self, chunk: NDArray[np.float32]) -> None:
        """Write a single float32 chunk; blocks when the device buffer is full.

        Chunk shape must match :attr:`channels`: ``(N,)`` for mono,
        ``(N, channels)`` otherwise.

        Raises:
            RuntimeError: Mic is closed, or libpulse / WASAPI surfaced a
                write failure.
            ValueError: dtype is not float32, ``ndim`` is not 1 or 2,
                or chunk channel count disagrees with :attr:`channels`.
        """
        if self._closed:
            raise RuntimeError("Mic is closed")
        _validate_chunk(chunk, expected_channels=self._channels)
        self._player.play(chunk)  # pyright: ignore[reportUnknownMemberType]

    def close(self) -> None:
        """Release the underlying soundcard player. Idempotent.

        Safe to call after a constructor failure.
        """
        if self._closed:
            return
        self._closed = True
        player_cm = self._player_cm
        if player_cm is None:
            return
        self._player_cm = None
        self._player = None
        player_cm.__exit__(  # pyright: ignore[reportUnknownMemberType]
            None, None, None
        )

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

    def __del__(self) -> None:
        # Best-effort finaliser: at interpreter shutdown soundcard /
        # numpy may already be torn down, so swallow everything.
        try:
            self.close()
        except BaseException:
            pass
