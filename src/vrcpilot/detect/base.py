"""Detection engine ABC and the :class:`Detection` value type.

Engine coordinates are always image-local (origin = top-left of the
captured image). Mapping to desktop / window coordinates is the caller's
job, which keeps engines reusable for cropped or replayed inputs.
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

    Frozen so callers can stash detections across frames without
    worrying about engines mutating them after the fact.

    Attributes:
        polygon: 4 corners ordered TL, TR, BR, BL. General
            quadrilateral (rotated, perspective-projected, etc.) —
            not constrained to be axis-aligned.
        confidence: Engine-normalised score in ``[0.0, 1.0]``;
            higher = stronger match. Exact meaning is engine-defined,
            so cross-engine thresholds do not transfer.
        scale: Size of the match relative to the query (``1.0``
            means the query was matched at its native size).
        rotation: Radians, counter-clockwise positive, of the match
            relative to the upright query.
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
        """Axis-aligned ``(x, y, width, height)`` in pixels.

        Rounded to ``int`` so it can be handed straight to OpenCV
        drawing primitives and pixel-indexed array slicing, both of
        which reject sub-pixel coordinates. ``width`` and ``height``
        are non-negative (zero for a degenerate polygon).
        """
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
        """Polygon centroid as ``(x, y)`` in pixels.

        Vertex mean rather than bbox center so rotated quadrilaterals
        still report a click target on the visible mark; for axis-aligned
        boxes the two coincide. Kept as ``float`` so callers can decide
        whether to round before feeding :func:`mouse.move`.
        """
        mean_x = sum(p[0] for p in self.polygon) / 4
        mean_y = sum(p[1] for p in self.polygon) / 4
        return (float(mean_x), float(mean_y))


class DetectEngine(ABC):
    """Swappable detection backend.

    Subclass to plug in alternative matchers (feature-based,
    learned, ...) alongside the built-in
    :class:`vrcpilot.detect.TemplateDetectEngine`.
    """

    @abstractmethod
    def detect(
        self,
        image: NDArray[np.uint8],
        query: NDArray[np.uint8],
    ) -> Sequence[Detection]:
        """Locate instances of *query* within *image*.

        Both arrays must be ``(H, W, 3)`` uint8 RGB; coordinates of
        returned :class:`Detection` objects are image-local. Empty
        sequence on no match (implementations must not raise).
        """
