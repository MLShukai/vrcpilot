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
    """Platform-specific audio source for the speaker modality.

    Implementations stream VRChat application audio and expose it as
    float32 PCM. The public wrapper owns closed-state checks and the
    context-manager protocol; backends only need to open in
    ``__init__`` and release in :meth:`close`.
    """

    @abstractmethod
    def read(self) -> NDArray[np.float32]:
        """Return all samples accumulated since the previous read.

        Shape ``(N, CHANNELS)``, dtype ``float32``, sample rate
        ``SAMPLE_RATE`` Hz. ``N`` may be ``0`` if no samples are
        available yet.
        """

    @abstractmethod
    def close(self) -> None:
        """Release platform resources.

        Must be idempotent and not raise.
        """
