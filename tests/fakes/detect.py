"""Detect-related test doubles.

Stand-in for :class:`vrcpilot.detect.DetectEngine` used by Phase 2C /
Phase 3 tests where exercising the real OpenCV ``TM_CCOEFF_NORMED``
backend is irrelevant -- ``FakeDetectEngine`` returns a pre-baked list
of :class:`Detection` from every :meth:`detect` call regardless of the
input image, while recording call counts and the last ``image`` /
``query`` so tests can assert what the engine saw.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import override

import numpy as np
from numpy.typing import NDArray

from vrcpilot.detect import DetectEngine, Detection


class FakeDetectEngine(DetectEngine):
    """Engine that returns a fixed detection list, recording call inputs.

    :attr:`calls`, :attr:`last_image`, :attr:`last_query` let tests
    assert how often the engine ran and what it saw.
    """

    def __init__(self, detections: Sequence[Detection]) -> None:
        self._detections: list[Detection] = list(detections)
        self.calls: int = 0
        self.last_image: NDArray[np.uint8] | None = None
        self.last_query: NDArray[np.uint8] | None = None

    @override
    def detect(
        self,
        image: NDArray[np.uint8],
        query: NDArray[np.uint8],
    ) -> Sequence[Detection]:
        self.calls += 1
        self.last_image = image
        self.last_query = query
        return list(self._detections)
