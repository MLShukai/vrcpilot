"""Render an :class:`OCRResult` onto a copy of its screenshot image.

The output is an RGB ``uint8`` ndarray suitable for
``PIL.Image.fromarray``; the screenshot inside the result is never
mutated. When ``text_color`` is ``None`` each word picks black or
white by sampling its pre-draw bbox luminance, avoiding unreadable
white-on-white / black-on-black overlays without caller involvement.
"""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from .recognize import OCRResult


def _decide_text_color(
    original: NDArray[np.uint8],
    bbox: tuple[int, int, int, int],
) -> tuple[int, int, int]:
    """Pick black or white based on the mean luminance of *bbox*.

    A bbox fully outside the image is treated as bright (black text),
    matching the "readable on white" default when no signal exists.
    """
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
    result: OCRResult,
    *,
    box_color: tuple[int, int, int] = (0, 255, 0),
    text_color: tuple[int, int, int] | None = None,
    font_scale: float = 0.6,
    thickness: int = 2,
) -> NDArray[np.uint8]:
    """Draw OCR detections onto a copy of the screenshot image.

    Each word becomes a polygon outline in ``box_color`` plus its text
    placed just above the bbox (or just below when the top edge has no
    room). Colors are RGB end-to-end, so ``(0, 255, 0)`` saves as green
    via ``PIL.Image.fromarray``. ``text_color=None`` picks black or
    white per word from the underlying patch luminance. The input
    image is never mutated.
    """
    original = result.screenshot.image
    canvas: NDArray[np.uint8] = original.copy()

    for word in result.words:
        polygon_pts = np.array(word.polygon, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(
            canvas,
            [polygon_pts],
            isClosed=True,
            color=box_color,
            thickness=thickness,
        )

        bbox = word.bbox
        chosen_color: tuple[int, int, int] = (
            text_color if text_color is not None else _decide_text_color(original, bbox)
        )

        bx, by, _bw, bh = bbox
        # Only the text height is used for the above/below choice;
        # width and baseline are returned by the API but irrelevant here.
        (_text_w, text_h), _baseline = cv2.getTextSize(
            word.text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
        )
        # Prefer placing text above the bbox; fall back below when
        # the top edge lacks the height to fit it.
        if by - text_h - 4 >= 0:
            text_y = by - 4
        else:
            text_y = by + bh + text_h + 4
        cv2.putText(
            canvas,
            word.text,
            (bx, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            chosen_color,
            thickness,
            cv2.LINE_AA,
        )

    return canvas
