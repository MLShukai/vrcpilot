"""OCR engine ABC and the :class:`OCRWord` value type.

Coordinates are image-local (top-left origin). For VRChat window
screenshots this matches the window-local frame consumed by
:func:`vrcpilot.controls.mouse.move`, so values are click-ready.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vrcpilot.types import Polygon


@dataclass(frozen=True)
class OCRWord:
    """Single OCR detection in image-local coordinates.

    ``polygon`` is a 4-vertex quad in TL, TR, BR, BL order — a general
    quadrilateral is used (not an axis-aligned rect) so rotated text
    survives the round trip. ``confidence`` is on ``[0.0, 1.0]``.
    """

    text: str
    polygon: Polygon
    confidence: float

    def __post_init__(self) -> None:
        # Static typing pins the length at 4, but downstream callers
        # can construct via ``cast`` or runtime tuple-building, so we
        # guard at construction time too.
        if len(self.polygon) != 4:
            raise ValueError(
                f"OCRWord.polygon must have exactly 4 points; "
                f"got {len(self.polygon)}"
            )

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """Axis-aligned bounding box as ``(x, y, width, height)`` in pixels.

        ``width`` / ``height`` are non-negative (zero for a degenerate
        polygon).
        """
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        x_min = min(xs)
        x_max = max(xs)
        y_min = min(ys)
        y_max = max(ys)
        return (
            int(round(x_min)),
            int(round(y_min)),
            int(round(x_max - x_min)),
            int(round(y_max - y_min)),
        )

    @property
    def center(self) -> tuple[float, float]:
        """Polygon centroid as ``(x, y)`` in image-local pixels."""
        mean_x = sum(p[0] for p in self.polygon) / 4
        mean_y = sum(p[1] for p in self.polygon) / 4
        return (float(mean_x), float(mean_y))


class OCREngine(ABC):
    """Swappable OCR backend.

    Subclass this to plug in non-default engines (PaddleOCR, Tesseract,
    cloud APIs, ...) alongside the built-in :class:`RapidOCREngine`.
    """

    @abstractmethod
    def recognize(self, image: NDArray[np.uint8]) -> Sequence[OCRWord]:
        """Recognize text in an ``(H, W, 3)`` uint8 RGB image.

        Returned :class:`OCRWord` coordinates are image-local; mapping
        them to desktop coordinates is the caller's responsibility.
        """
