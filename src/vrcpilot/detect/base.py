"""Detection engine ABC and the :class:`Detection` value type.

Engine coordinates are always image-local (origin = top-left of the
captured image); the engine never translates to desktop coordinates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vrcpilot.types import Polygon


@dataclass(frozen=True)
class Detection:
    """Single detection in image-local coordinates.

    ``polygon`` is 4 corners ordered TL, TR, BR, BL; arbitrary
    quadrilaterals (e.g. homography-projected) are allowed.
    ``confidence`` is engine-defined in ``[0.0, 1.0]``. ``scale`` is
    relative to the query (``1.0`` = same size). ``rotation`` is in
    radians, counter-clockwise positive.
    """

    polygon: Polygon
    confidence: float
    scale: float
    rotation: float

    def __post_init__(self) -> None:
        # Tuples built dynamically can slip past the static length pin.
        if len(self.polygon) != 4:
            raise ValueError(
                f"Detection.polygon must have exactly 4 points; "
                f"got {len(self.polygon)}"
            )

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """Axis-aligned ``(x, y, width, height)`` in pixels."""
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        return (
            round(x_min),
            round(y_min),
            round(x_max - x_min),
            round(y_max - y_min),
        )

    @property
    def center(self) -> tuple[float, float]:
        """Polygon centroid (vertex mean) in pixels."""
        mean_x = sum(p[0] for p in self.polygon) / 4
        mean_y = sum(p[1] for p in self.polygon) / 4
        return (float(mean_x), float(mean_y))


class DetectEngine(ABC):
    """Abstract base for swappable detection backends."""

    @abstractmethod
    def detect(
        self,
        image: NDArray[np.uint8],
        query: NDArray[np.uint8],
    ) -> Sequence[Detection]:
        """Detect instances of *query* in *image*.

        Both arrays must be ``(H, W, 3)`` uint8 RGB.
        """
