"""Public :class:`Mic` session and module-level helpers.

Channels are not pinned at construction time: every call to
:meth:`Mic.play` infers the channel count from the first chunk's shape
and opens a fresh :class:`sounddevice.OutputStream` for that count.
The constructor only resolves and caches the output-device index.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from numpy.typing import NDArray

from vrcpilot.mic.base import SAMPLE_RATE
from vrcpilot.mic.devices import lookup_output_device, resolve_device_name


def _validate_chunk(
    chunk: NDArray[np.float32], *, expected_channels: int | None = None
) -> int:
    """Validate ``chunk`` and return its channel count.

    ``ndim == 1`` is treated as mono; ``ndim == 2`` interprets the
    second axis as channel count. Anything else is rejected.
    """
    if chunk.dtype != np.float32:
        raise ValueError(f"chunk dtype must be float32, got {chunk.dtype}")
    if chunk.ndim == 1:
        channels = 1
    elif chunk.ndim == 2:
        channels = int(chunk.shape[1])
    else:
        raise ValueError(
            f"chunk must be 1-D (mono) or 2-D (N, C), got ndim={chunk.ndim}"
        )
    if expected_channels is not None and channels != expected_channels:
        raise ValueError(
            f"chunk channel count {channels} disagrees with stream "
            f"channels {expected_channels}"
        )
    return channels


class Mic:
    """Session bound to a virtual-cable output device.

    The constructor resolves the device exactly once (argument >
    ``$VRCPILOT_MIC_DEVICE`` > OS-specific default) and caches the
    resolved sounddevice index; later :meth:`play` calls reuse it.

    Args:
        device: Device-name substring. ``None`` defers to env / default.

    Raises:
        MicDeviceNotFoundError: No output device matches the resolved
            name, or no default is configured for this platform.
        ImportError: ``sounddevice`` is not installed on the host
            (raised when :func:`lookup_output_device` performs its
            lazy import).
    """

    def __init__(self, device: str | None = None) -> None:
        self._device_name: str = resolve_device_name(device)
        self._device_index: int = lookup_output_device(self._device_name)

    @property
    def device_name(self) -> str:
        """The resolved device-name substring (post-argument/env/default
        chain)."""
        return self._device_name

    @property
    def device_index(self) -> int:
        """The sounddevice device index assigned to this session."""
        return self._device_index

    def play(
        self,
        stream: Iterable[NDArray[np.float32]],
        *,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        """Pull float32 chunks from ``stream`` and write them to the device.

        Channels are inferred from the first chunk's shape: ``(N,)`` is
        mono, ``(N, C)`` is ``C``-channel. Subsequent chunks must agree
        on the channel count or :class:`ValueError` is raised. Blocks
        until the iterator is exhausted and the underlying PortAudio
        stream has drained, so the caller can release resources right
        after the call returns.

        Args:
            stream: Iterable producing float32 NDArray chunks. Empty
                iterables are a no-op (no PortAudio stream is opened).
            sample_rate: Output rate in Hz. Default 48000.

        Raises:
            ValueError: dtype is not float32, ``ndim`` is not 1 or 2,
                or a later chunk's channel count disagrees with the
                first.
        """
        iterator = iter(stream)
        try:
            first = next(iterator)
        except StopIteration:
            return
        channels = _validate_chunk(first)
        import sounddevice as sd  # pyright: ignore[reportMissingTypeStubs]

        with sd.OutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            device=self._device_index,
        ) as out:
            out.write(first)  # pyright: ignore[reportUnknownMemberType]
            for chunk in iterator:
                _validate_chunk(chunk, expected_channels=channels)
                out.write(chunk)  # pyright: ignore[reportUnknownMemberType]


def play(
    stream: Iterable[NDArray[np.float32]],
    *,
    device: str | None = None,
    sample_rate: int = SAMPLE_RATE,
) -> None:
    """One-shot helper: equivalent to ``Mic(device).play(stream, ...)``."""
    Mic(device).play(stream, sample_rate=sample_rate)
