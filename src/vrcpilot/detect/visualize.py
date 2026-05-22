"""Render a :class:`DetectResult` onto a copy of its screenshot.

Label colour is auto-picked (black/white) per detection from patch
luminance unless the caller pins ``text_color``.
"""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from .detect import DetectResult


def _decide_text_color(
    original: NDArray[np.uint8],
    bbox: tuple[int, int, int, int],
) -> tuple[int, int, int]:
    """Black on bright patches, white on dark; out-of-bounds defaults to black
    (readable on the typical white margin)."""
    h, w = original.shape[:2]
    bx, by, bw, bh = bbox
    x0 = max(0, bx)
    y0 = max(0, by)
    x1 = min(w, bx + bw)
    y1 = min(h, by + bh)
    if x1 <= x0 or y1 <= y0:
        return (0, 0, 0)
    patch = original[y0:y1, x0:x1]
    gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
    mean = float(gray.mean())
    if mean > 128:
        return (0, 0, 0)
    return (255, 255, 255)


def render(
    result: DetectResult,
    *,
    box_color: tuple[int, int, int] = (0, 255, 0),
    text_color: tuple[int, int, int] | None = None,
    font_scale: float = 0.6,
    thickness: int = 2,
) -> NDArray[np.uint8]:
    """Draw detections as polygons with a confidence/scale label.

    Labels sit above the bbox when there is room, otherwise below
    (matching :func:`vrcpilot.ocr.render`). The screenshot is not
    mutated; a fresh copy is returned.
    """
    original = result.screenshot.image
    canvas: NDArray[np.uint8] = original.copy()

    for det in result.detections:
        polygon_pts = np.array(det.polygon, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(
            canvas,
            [polygon_pts],
            isClosed=True,
            color=box_color,
            thickness=thickness,
        )

        bbox = det.bbox
        chosen_color = (
            text_color if text_color is not None else _decide_text_color(original, bbox)
        )

        label = f"{det.confidence:.2f} x{det.scale:.2f}"

        bx, by, _bw, bh = bbox
        (_text_w, text_h), _baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
        )
        text_y = by - 4 if by - text_h - 4 >= 0 else by + bh + text_h + 4
        cv2.putText(
            canvas,
            label,
            (bx, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            chosen_color,
            thickness,
            cv2.LINE_AA,
        )

    return canvas
