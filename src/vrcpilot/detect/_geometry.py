"""IoU + NMS helpers shared by detect engines."""

from __future__ import annotations

from .base import Detection


def iou(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> float:
    """Axis-aligned IoU for ``(x, y, w, h)`` boxes; ``0.0`` if degenerate."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    inter_x0 = max(ax, bx)
    inter_y0 = max(ay, by)
    inter_x1 = min(ax + aw, bx + bw)
    inter_y1 = min(ay + ah, by + bh)
    iw = max(0, inter_x1 - inter_x0)
    ih = max(0, inter_y1 - inter_y0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return inter / union


def nms(
    detections: list[Detection],
    iou_threshold: float,
) -> list[Detection]:
    """Greedy NMS; drops a detection whose bbox IoU with any kept detection
    exceeds ``iou_threshold``.

    Output is confidence-descending.
    """
    if not detections:
        return []
    sorted_dets = sorted(detections, key=lambda d: d.confidence, reverse=True)
    kept: list[Detection] = []
    for det in sorted_dets:
        if any(iou(det.bbox, k.bbox) > iou_threshold for k in kept):
            continue
        kept.append(det)
    return kept
