"""Multi-scale template-matching detection engine.

VRChat UI is rendered pixel-perfect and its small (18-50 px) icons
defeat feature-based detectors; a scale-grid sweep of
``cv2.matchTemplate`` reaches them reliably, hence the default.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, override

import cv2
import numpy as np
from numpy.typing import NDArray

from vrcpilot.types import Polygon

from ._geometry import nms
from .base import DetectEngine, Detection


class TemplateDetectEngine(DetectEngine):
    """Multi-scale (+ optional rotation) template-matching engine.

    For each ``(scale, rotation)``, ``cv2.matchTemplate``
    (TM_CCOEFF_NORMED) scores the transformed query against the image;
    positions at or above ``threshold`` become candidates, NMS
    deduplicates. Use this for pixel-stable UI targets (VRChat icons);
    prefer feature-based detectors for photographic content.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.85,
        scales: Sequence[float] = (
            0.25,
            0.3,
            0.35,
            0.4,
            0.5,
            0.6,
            0.75,
            0.9,
            1.0,
            1.25,
            1.5,
            1.8,
            2.2,
            2.6,
            3.0,
        ),
        rotations_deg: Sequence[float] = (0.0,),
        nms_iou: float = 0.3,
        max_results: int = 32,
    ) -> None:
        """Configure the scale grid, rotation list, threshold and NMS.

        ``threshold`` is the ``TM_CCOEFF_NORMED`` cutoff (theoretical
        range ``[-1, 1]``); ``0.85`` is tuned for VRChat Launch Pad
        icons. The default ``scales`` grid spans ``0.25``-``3.0`` so a
        fixed query matches captures from HD (1280x720) to 4K, denser
        at the low end where HD icons land. ``rotations_deg`` defaults
        to ``(0.0,)`` because VRChat UI never rotates; enumerating more
        angles multiplies the cost. ``nms_iou`` is the IoU above which
        a lower-confidence candidate is suppressed.
        """
        self._threshold = threshold
        self._scales = tuple(scales)
        self._rotations_deg = tuple(rotations_deg)
        self._nms_iou = nms_iou
        self._max_results = max_results

    @override
    def detect(
        self,
        image: NDArray[np.uint8],
        query: NDArray[np.uint8],
    ) -> Sequence[Detection]:
        """Detect instances of *query* in *image*.

        Empty when nothing clears ``threshold`` or the query exceeds
        the image at every transform.
        """
        # Match in RGB so the score reflects colour similarity, not just
        # luminance shape. A blue icon and a red icon with the same outline
        # both pass a grayscale TM_CCOEFF_NORMED at high scores; the 3-channel
        # variant penalises the colour mismatch.
        img_h, img_w = image.shape[:2]
        candidates: list[Detection] = []

        for scale in self._scales:
            scaled = _resize_query(query, scale)
            if scaled is None:
                continue

            for rot_deg in self._rotations_deg:
                transformed = _rotate_query(scaled, rot_deg)
                if transformed is None:
                    continue
                t_h, t_w = transformed.shape[:2]
                if t_h > img_h or t_w > img_w:
                    continue

                score_map: Any = cv2.matchTemplate(
                    image, transformed, cv2.TM_CCOEFF_NORMED
                )
                ys, xs = np.where(score_map >= self._threshold)
                rotation_rad = -math.radians(rot_deg)
                for x_int, y_int in zip(xs.tolist(), ys.tolist()):
                    score = float(score_map[y_int, x_int])
                    polygon = _build_polygon(x=x_int, y=y_int, width=t_w, height=t_h)
                    candidates.append(
                        Detection(
                            polygon=polygon,
                            confidence=float(np.clip(score, 0.0, 1.0)),
                            scale=float(scale),
                            rotation=rotation_rad,
                        )
                    )

        deduped = nms(candidates, self._nms_iou)
        return deduped[: self._max_results]


def _resize_query(
    query: NDArray[Any],
    scale: float,
) -> NDArray[Any] | None:
    """Resize ``query``; ``None`` if the result is smaller than 2x2.

    Typed as ``NDArray[Any]`` because ``cv2`` returns ``MatLike``,
    which pyright strict cannot narrow.
    """
    h, w = query.shape[:2]
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    # cv2 docs: INTER_AREA shrinks cleanly, INTER_CUBIC enlarges sharply.
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized: Any = cv2.resize(query, (new_w, new_h), interpolation=interp)
    if resized.shape[0] < 2 or resized.shape[1] < 2:
        return None
    return resized


def _rotate_query(
    query: NDArray[Any],
    rotation_deg: float,
) -> NDArray[Any] | None:
    """Rotate ``query`` around its centre with a grown 0-padded canvas.

    Identity rotation short-circuits.
    """
    if rotation_deg == 0.0:
        return query

    h, w = query.shape[:2]
    center = (w / 2.0, h / 2.0)
    rot_mat = cv2.getRotationMatrix2D(center, rotation_deg, 1.0)
    cos = abs(float(rot_mat[0, 0]))
    sin = abs(float(rot_mat[0, 1]))
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    if new_w < 2 or new_h < 2:
        return None
    rot_mat[0, 2] += new_w / 2 - center[0]
    rot_mat[1, 2] += new_h / 2 - center[1]
    rotated: Any = cv2.warpAffine(query, rot_mat, (new_w, new_h), borderValue=0)
    return rotated


def _build_polygon(
    *,
    x: int,
    y: int,
    width: int,
    height: int,
) -> Polygon:
    """TL,TR,BR,BL polygon framing the rotated-template canvas.

    The score-map peak aligns with this canvas, not the unrotated query.
    """
    return (
        (float(x), float(y)),
        (float(x + width), float(y)),
        (float(x + width), float(y + height)),
        (float(x), float(y + height)),
    )
