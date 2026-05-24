"""Integration-real tests for
:class:`vrcpilot.detect.template.TemplateDetectEngine`.

Exercises the real OpenCV ``cv2.matchTemplate``
(``TM_CCOEFF_NORMED``) plus the engine's scale grid, rotation grid,
NMS dedupe, and max_results cap. Targets are synthesised pixel-perfect
shapes on a flat background — this mirrors how VRChat UI icons look
(pixel-stable, no photographic noise) and gives ground-truth centres
that are trivial to assert against.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest
from numpy.typing import NDArray

from vrcpilot.detect import Detection, TemplateDetectEngine


def _make_flat_background(
    height: int = 480,
    width: int = 640,
    color: tuple[int, int, int] = (40, 40, 40),
) -> NDArray[np.uint8]:
    """Solid-colour RGB ``uint8`` canvas.

    A flat background isolates the icon under test from feature noise,
    matching the VRChat Launch Pad backdrop.
    """
    return np.full((height, width, 3), color, dtype=np.uint8)


def _make_simple_icon(size: int = 40) -> NDArray[np.uint8]:
    """High-contrast icon: white frame + blue square + yellow circle + cross.

    Mirrors the ~50 px VRChat Launch Pad icon shape that template
    matching is tuned for. Feature-based detectors would find few
    keypoints on such a target; template matching is stable here.
    """
    icon: NDArray[np.uint8] = np.full((size, size, 3), 255, dtype=np.uint8)
    cv2.rectangle(icon, (4, 4), (size - 4, size - 4), (20, 80, 200), -1)
    cv2.circle(icon, (size // 2, size // 2), size // 4, (250, 250, 50), -1)
    cv2.line(icon, (4, 4), (size - 4, size - 4), (10, 10, 10), 2)
    cv2.line(icon, (4, size - 4), (size - 4, 4), (10, 10, 10), 2)
    return icon


def _blit_bounded(
    dst: NDArray[np.uint8],
    src: NDArray[np.uint8],
    x: int,
    y: int,
) -> None:
    """In-place copy ``src`` into ``dst`` at ``(x, y)``, clipped to bounds.

    Out-of-bounds portions of ``src`` are silently dropped, matching
    how a partly-off-canvas paste behaves.
    """
    dh, dw = dst.shape[:2]
    sh, sw = src.shape[:2]
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(dw, x + sw)
    y1 = min(dh, y + sh)
    if x0 >= x1 or y0 >= y1:
        return
    dst[y0:y1, x0:x1] = src[y0 - y : y1 - y, x0 - x : x1 - x]


def _paste_at(
    bg: NDArray[np.uint8],
    icon: NDArray[np.uint8],
    x: int,
    y: int,
    *,
    scale: float = 1.0,
) -> tuple[NDArray[np.uint8], tuple[float, float]]:
    """Resize ``icon`` then paste at ``(x, y)`` top-left.

    Returns ``(image, (cx, cy))`` where ``(cx, cy)`` is the centre of
    the pasted region in image-local coordinates.
    """
    out = bg.copy()
    h, w = icon.shape[:2]
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(icon, (new_w, new_h), interpolation=interp)
    _blit_bounded(out, resized, x, y)
    return out, (x + new_w / 2.0, y + new_h / 2.0)


def _paste_rotated(
    bg: NDArray[np.uint8],
    icon: NDArray[np.uint8],
    rotation_deg: float,
    x: int,
    y: int,
) -> tuple[NDArray[np.uint8], tuple[float, float]]:
    """Rotate ``icon`` and paste at ``(x, y)``.

    Rotated bbox is computed first so the paste location matches the
    target the engine would search for at that rotation.
    """
    out = bg.copy()
    h, w = icon.shape[:2]
    center = (w / 2.0, h / 2.0)
    rot_mat = cv2.getRotationMatrix2D(center, rotation_deg, 1.0)
    cos = abs(float(rot_mat[0, 0]))
    sin = abs(float(rot_mat[0, 1]))
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    rot_mat[0, 2] += new_w / 2 - center[0]
    rot_mat[1, 2] += new_h / 2 - center[1]
    warped = cv2.warpAffine(icon, rot_mat, (new_w, new_h), borderValue=(40, 40, 40))
    _blit_bounded(out, warped, x, y)
    return out, (x + new_w / 2.0, y + new_h / 2.0)


def _recolor_icon(
    icon: NDArray[np.uint8],
    *,
    body_color: tuple[int, int, int],
    accent_color: tuple[int, int, int],
) -> NDArray[np.uint8]:
    """Rebuild the simple icon with different fill colours but identical shape.

    Used to verify that RGB matching penalises a colour-only change.
    Grayscale matching would treat the colour-swapped variant as a hit
    because TM_CCOEFF_NORMED is brightness-invariant; the 3-channel
    variant the engine uses scores the colour mismatch low enough to
    suppress it.
    """
    size = icon.shape[0]
    recoloured: NDArray[np.uint8] = np.full((size, size, 3), 255, dtype=np.uint8)
    cv2.rectangle(recoloured, (4, 4), (size - 4, size - 4), body_color, -1)
    cv2.circle(recoloured, (size // 2, size // 2), size // 4, accent_color, -1)
    cv2.line(recoloured, (4, 4), (size - 4, size - 4), (10, 10, 10), 2)
    cv2.line(recoloured, (4, size - 4), (size - 4, 4), (10, 10, 10), 2)
    return recoloured


class TestTemplateDetectEngineBasicHit:
    def test_identical_paste_is_localised_within_two_pixels(self):
        # Pixel-perfect paste: the best detection's centre should land
        # extremely close to the ground-truth centre.
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, (true_cx, true_cy) = _paste_at(bg, icon, 200, 150)
        engine = TemplateDetectEngine()

        dets = engine.detect(img, icon)

        assert len(dets) >= 1
        best = max(dets, key=lambda d: d.confidence)
        assert abs(best.center[0] - true_cx) < 2
        assert abs(best.center[1] - true_cy) < 2

    def test_identical_paste_yields_high_confidence(self):
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, _ = _paste_at(bg, icon, 200, 150)
        engine = TemplateDetectEngine()

        dets = engine.detect(img, icon)

        assert len(dets) >= 1
        best = max(dets, key=lambda d: d.confidence)
        assert best.confidence > 0.9

    def test_identity_match_reports_scale_near_one_and_zero_rotation(self):
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, _ = _paste_at(bg, icon, 200, 150)
        engine = TemplateDetectEngine()

        dets = engine.detect(img, icon)

        best = max(dets, key=lambda d: d.confidence)
        assert 0.9 < best.scale < 1.1
        assert abs(best.rotation) < 1e-6

    def test_returned_objects_are_Detection_instances(self):
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, _ = _paste_at(bg, icon, 200, 150)
        engine = TemplateDetectEngine()

        dets = engine.detect(img, icon)

        assert all(isinstance(d, Detection) for d in dets)

    def test_polygon_corners_are_finite_and_inside_image(self):
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, _ = _paste_at(bg, icon, 200, 150)
        engine = TemplateDetectEngine()

        dets = engine.detect(img, icon)

        assert len(dets) >= 1
        for x, y in dets[0].polygon:
            assert math.isfinite(x)
            assert math.isfinite(y)
            assert -1 < x < 641
            assert -1 < y < 481


class TestTemplateDetectEngineScaleRecovery:
    @pytest.mark.parametrize("scale", [0.5, 0.6, 1.0, 1.25])
    def test_engine_recovers_scale_within_grid_tolerance(self, scale: float):
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, (true_cx, true_cy) = _paste_at(bg, icon, 250, 200, scale=scale)
        engine = TemplateDetectEngine()

        dets = engine.detect(img, icon)

        assert len(dets) >= 1
        best = max(dets, key=lambda d: d.confidence)
        # Nearest-neighbour on the scale grid leaves a few-pixel
        # centre error; grid step is ~0.1 so scale tolerance is 0.15.
        assert abs(best.center[0] - true_cx) < 5
        assert abs(best.center[1] - true_cy) < 5
        assert abs(best.scale - scale) <= 0.15


class TestTemplateDetectEngineRotationRecovery:
    def test_engine_recovers_rotation_when_grid_lists_it(self):
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, (true_cx, true_cy) = _paste_rotated(bg, icon, 30.0, 250, 200)
        # Default ``rotations_deg=(0.0,)`` would miss this; the test
        # spec is the engine recovers rotation only when listed.
        engine = TemplateDetectEngine(rotations_deg=(0.0, 30.0, -30.0))

        dets = engine.detect(img, icon)

        assert len(dets) >= 1
        best = max(dets, key=lambda d: d.confidence)
        assert abs(best.center[0] - true_cx) < 6
        assert abs(best.center[1] - true_cy) < 6
        # ``Detection.rotation`` is in radians, CCW positive. The
        # template matches at rot_deg=+30, so rotation = -pi/6.
        expected_rad = -math.radians(30.0)
        diff = (best.rotation - expected_rad + math.pi) % (2 * math.pi) - math.pi
        assert abs(diff) < 1e-6


class TestTemplateDetectEngineMultiInstance:
    def test_two_pasted_instances_are_both_detected(self):
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, c1 = _paste_at(bg, icon, 80, 80)
        img, c2 = _paste_at(img, icon, 380, 250)
        engine = TemplateDetectEngine()

        dets = engine.detect(img, icon)

        assert len(dets) >= 2
        # Each ground-truth centre must match at least one detection.
        for truth in (c1, c2):
            assert any(
                abs(d.center[0] - truth[0]) < 4 and abs(d.center[1] - truth[1]) < 4
                for d in dets
            )


class TestTemplateDetectEngineNoMatch:
    def test_query_absent_from_image_returns_no_detections(self):
        bg = _make_flat_background()
        icon = _make_simple_icon()
        engine = TemplateDetectEngine()

        dets = engine.detect(bg, icon)

        assert list(dets) == []

    def test_query_too_large_at_every_scale_returns_no_detections(self):
        # 100x100 image, 200x200 query; with scales >= 1.0 the
        # transformed template never fits and the engine must skip
        # cleanly without raising.
        small_image: NDArray[np.uint8] = np.full((100, 100, 3), 40, dtype=np.uint8)
        big_query: NDArray[np.uint8] = np.full((200, 200, 3), 255, dtype=np.uint8)
        engine = TemplateDetectEngine(scales=(1.0, 1.5))

        dets = engine.detect(small_image, big_query)

        assert list(dets) == []


class TestTemplateDetectEngineMaxResults:
    def test_max_results_caps_returned_detections(self):
        # Two pasted instances would normally yield >= 2 hits;
        # max_results=1 forces the engine to truncate.
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, _ = _paste_at(bg, icon, 80, 80)
        img, _ = _paste_at(img, icon, 380, 250)
        engine = TemplateDetectEngine(max_results=1)

        dets = engine.detect(img, icon)

        assert len(dets) <= 1


class TestTemplateDetectEngineColorDiscrimination:
    def test_rgb_matching_rejects_a_colour_only_variant(self):
        # Same outline / cross / circle shape, swapped fill colours.
        # A grayscale TM_CCOEFF_NORMED would accept both because it is
        # brightness-invariant; the engine matches in RGB so the
        # colour mismatch must score the variant out of the result.
        query = _make_simple_icon()
        variant = _recolor_icon(
            query, body_color=(200, 30, 30), accent_color=(40, 200, 200)
        )
        bg = _make_flat_background()
        img, (true_cx, true_cy) = _paste_at(bg, query, 100, 100)
        img, (variant_cx, variant_cy) = _paste_at(img, variant, 380, 250)
        engine = TemplateDetectEngine()

        dets = engine.detect(img, query)

        # The query paste is hit.
        assert any(
            abs(d.center[0] - true_cx) < 4 and abs(d.center[1] - true_cy) < 4
            for d in dets
        )
        # The colour-swapped variant is rejected.
        assert not any(
            abs(d.center[0] - variant_cx) < 4 and abs(d.center[1] - variant_cy) < 4
            for d in dets
        )


class TestTemplateDetectEngineNMS:
    def test_default_threshold_does_not_emit_overlapping_duplicates(self):
        # A single pasted icon naturally produces many neighbouring
        # high-score positions in the score map. NMS at the default
        # iou=0.3 must dedupe so the engine returns a small number of
        # distinct detections, not the full neighbourhood.
        bg = _make_flat_background()
        icon = _make_simple_icon()
        img, (true_cx, true_cy) = _paste_at(bg, icon, 200, 150)
        engine = TemplateDetectEngine()

        dets = engine.detect(img, icon)

        # A single paste should not produce more than a handful of
        # detections; deduplication keeps the count small.
        assert 1 <= len(dets) <= 5
        # At least one detection still matches the ground-truth centre.
        assert any(
            abs(d.center[0] - true_cx) < 4 and abs(d.center[1] - true_cy) < 4
            for d in dets
        )
