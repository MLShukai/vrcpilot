"""Audio-modality core types: backend ABC and format constants."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Final

import numpy as np
from numpy.typing import NDArray

#: Sampling rate produced by every :class:`SpeakerBackend`, in Hz.
SAMPLE_RATE: Final[int] = 48000

#: Channel count of the interleaved ndarray returned by
#: :meth:`SpeakerBackend.read` (stereo).
CHANNELS: Final[int] = 2

#: Element dtype of arrays returned by :meth:`SpeakerBackend.read`.
DTYPE: Final = np.float32


class SpeakerBackend(ABC):
    """Platform-specific audio source for :class:`Speaker`.

    Backends open in ``__init__`` and release in :meth:`close`; the
    public wrapper handles closed-state checks and the context-manager
    protocol.
    """

    @abstractmethod
    def read(self) -> NDArray[np.float32]:
        """Return every sample buffered since the previous read.

        Shape is ``(N, CHANNELS)``; an empty ``(0, CHANNELS)`` array is
        the contract's "no new audio within the backend's timeout"
        signal, not an error.
        """

    @abstractmethod
    def close(self) -> None:
        """Release platform resources.

        Must be idempotent and must not raise; the public wrapper and
        ``ExitStack`` rollback paths can invoke it more than once.
        """
