"""Public :class:`Mic` session.

The constructor opens a sounddevice :class:`OutputStream` for a fixed
``(sample_rate, channels)`` and starts it; :meth:`play` writes a single
float32 chunk per call so callers drive the cadence with their own loop
(``for chunk in tts.stream(): mic.play(chunk)``). The stream is released
in :meth:`close`, when the ``with`` block exits, or when the instance is
garbage-collected.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import numpy as np
from numpy.typing import NDArray

from vrcpilot.mic.base import SAMPLE_RATE
from vrcpilot.mic.devices import lookup_output_device, resolve_device_name


def _validate_chunk(chunk: NDArray[np.float32], *, expected_channels: int) -> None:
    """Validate dtype/shape of ``chunk`` against ``expected_channels``."""
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

    The constructor resolves the device, opens a
    :class:`sounddevice.OutputStream` for the configured
    ``sample_rate`` / ``channels``, and starts it. Each :meth:`play`
    call writes a single chunk; the stream stays open until
    :meth:`close`, the ``with`` block exits, or the instance is
    garbage-collected.

    Args:
        device: Device-name substring. ``None`` defers to env / default.
        sample_rate: Output rate in Hz. Default 48000.
        channels: Output channel count baked into the stream. Default 1.

    Raises:
        MicDeviceNotFoundError: No output device matches the resolved
            name, or no default is configured for this platform.
        ImportError: ``sounddevice`` is not installed on the host.
        ValueError: ``sample_rate`` or ``channels`` is not strictly
            positive.
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
        self._stream: Any = None
        self._device_name: str = resolve_device_name(device)
        self._device_index: int = lookup_output_device(self._device_name)
        self._sample_rate: int = sample_rate
        self._channels: int = channels
        import sounddevice as sd  # pyright: ignore[reportMissingTypeStubs]

        self._stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            device=self._device_index,
        )
        self._stream.start()  # pyright: ignore[reportUnknownMemberType]

    @property
    def device_name(self) -> str:
        """The resolved device-name substring."""
        return self._device_name

    @property
    def device_index(self) -> int:
        """The sounddevice device index assigned to this session."""
        return self._device_index

    @property
    def sample_rate(self) -> int:
        """Sample rate baked into the underlying OutputStream."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Channel count baked into the underlying OutputStream."""
        return self._channels

    def play(self, chunk: NDArray[np.float32]) -> None:
        """Write a single float32 chunk to the device.

        Blocks if PortAudio's internal buffer is full. The chunk shape
        must match the configured channel count (``(N,)`` for mono,
        ``(N, channels)`` for multi-channel).

        Raises:
            RuntimeError: Mic is already closed.
            ValueError: dtype is not float32, ``ndim`` is not 1 or 2,
                or the chunk channel count disagrees with
                :attr:`channels`.
        """
        if self._closed:
            raise RuntimeError("Mic is closed")
        _validate_chunk(chunk, expected_channels=self._channels)
        self._stream.write(chunk)  # pyright: ignore[reportUnknownMemberType]

    def close(self) -> None:
        """Stop and close the underlying OutputStream.

        Idempotent; safe to call multiple times or after a constructor
        failure (in which case no stream was ever opened).
        """
        if self._closed:
            return
        self._closed = True
        stream = self._stream
        if stream is None:
            return
        self._stream = None
        stream.stop()  # pyright: ignore[reportUnknownMemberType]
        stream.close()  # pyright: ignore[reportUnknownMemberType]

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
        # Best-effort finaliser. Suppress everything: interpreter
        # shutdown may have already torn down sounddevice / numpy.
        try:
            self.close()
        except BaseException:
            pass
