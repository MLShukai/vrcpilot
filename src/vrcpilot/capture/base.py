"""Abstract base class for VRChat window capture backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class CaptureBackend(ABC):
    """Platform-specific frame source for :class:`vrcpilot.Capture`.

    The public :class:`vrcpilot.Capture` wrapper owns closed-state
    checks and the context-manager protocol; backends only need to
    open in ``__init__`` and release in :meth:`close`.
    """

    @abstractmethod
    def read(self) -> np.ndarray:
        """Return the latest frame as an ``(H, W, 3)`` uint8 RGB ndarray.

        Backends may block (WGC waits for a callback) or be synchronous
        (X11 re-grabs on demand); the public :class:`Capture` surface
        hides the difference but implementers must pick one mode.
        """

    @abstractmethod
    def close(self) -> None:
        """Release platform resources; must be idempotent and never raise."""
