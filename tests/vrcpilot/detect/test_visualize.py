"""Tests for :mod:`vrcpilot.detect.visualize`.

Integration-real with the real OpenCV drawing primitives. The function
is a pure ndarray -> ndarray transform: verification looks at shape,
dtype, immutability of the source, and which pixel colours appear in the
diff against the input.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from numpy.typing import NDArray

from vrcpilot.detect import Detection, DetectResult, Polygon, render
from vrcpilot.screenshot import Screenshot


def _make_screenshot(image: NDArray[np.uint8]) -> Screenshot:
    height, width = image.shape[:2]
    return Screenshot(
        image=image,
        x=0,
        y=0,
        width=width,
        height=height,
        monitor_index=1,
        captured_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
    )


def _make_result(
    image: NDArray[np.uint8],
    *,
    polygon: Polygon = (
        (10.0, 30.0),
        (60.0, 30.0),
        (60.0, 50.0),
        (10.0, 50.0),
    ),
    confidence: float = 0.92,
    scale: float = 1.25,
    rotation: float = 0.0,
) -> DetectResult:
    det = Detection(
        polygon=polygon,
        confidence=confidence,
        scale=scale,
        rotation=rotation,
    )
    query: NDArray[np.uint8] = np.zeros((4, 4, 3), dtype=np.uint8)
    return DetectResult(
        screenshot=_make_screenshot(image),
        query=query,
        detections=(det,),
    )


def _full(value: int, shape: tuple[int, int, int] = (100, 200, 3)) -> NDArray[np.uint8]:
    return np.full(shape, value, dtype=np.uint8)


class TestRenderShapeAndDtype:
    def test_output_shape_matches_screenshot_image(self):
        image = _full(255)
        result = _make_result(image)

        out = render(result)

        assert out.shape == image.shape

    def test_output_dtype_is_uint8(self):
        image = _full(255)
        result = _make_result(image)

        out = render(result)

        assert out.dtype == np.uint8


class TestRenderIsPure:
    def test_source_image_is_not_mutated(self):
        image = _full(255)
        snapshot = image.copy()
        result = _make_result(image)

        render(result)

        assert np.array_equal(image, snapshot)

    def test_returned_array_is_a_fresh_copy(self):
        # Documented "screenshot is never mutated"; even empty
        # detections return a new array distinct from the source.
        image = _full(128)
        shot = _make_screenshot(image)
        query: NDArray[np.uint8] = np.zeros((4, 4, 3), dtype=np.uint8)
        result = DetectResult(screenshot=shot, query=query, detections=())

        out = render(result)

        assert out is not image


class TestRenderDrawsForEachDetection:
    def test_non_empty_detections_produce_pixel_diff(self):
        image = _full(255)
        result = _make_result(image)

        out = render(result)

        diff = (out != image).any(axis=-1)
        assert int(diff.sum()) > 0

    def test_empty_detections_returns_canvas_unchanged(self):
        image = _full(128)
        shot = _make_screenshot(image)
        query: NDArray[np.uint8] = np.zeros((4, 4, 3), dtype=np.uint8)
        result = DetectResult(screenshot=shot, query=query, detections=())

        out = render(result)

        assert np.array_equal(out, image)


class TestRenderAutoContrastTextColor:
    def test_white_background_draws_dark_label_for_legibility(self):
        image = _full(255)
        result = _make_result(image)

        out = render(result)

        diff_mask = (out != image).any(axis=-1)
        changed = out[diff_mask]
        near_black = (changed.sum(axis=-1) < 60).sum()
        assert near_black > 0

    def test_black_background_draws_light_label_for_legibility(self):
        image = _full(0)
        result = _make_result(image)

        out = render(result)

        diff_mask = (out != image).any(axis=-1)
        changed = out[diff_mask]
        near_white = (changed.sum(axis=-1) > 700).sum()
        assert near_white > 0


class TestRenderExplicitTextColor:
    def test_caller_text_color_overrides_auto_contrast(self):
        image = _full(255)
        result = _make_result(image)

        out = render(result, text_color=(255, 0, 0))

        diff_mask = (out != image).any(axis=-1)
        changed = out[diff_mask]
        red_pixels = (
            (changed[:, 0] > 200) & (changed[:, 1] < 60) & (changed[:, 2] < 60)
        ).sum()
        assert red_pixels > 0

    def test_caller_box_color_appears_in_output(self):
        image = _full(255)
        result = _make_result(image)

        out = render(result, box_color=(0, 0, 255), text_color=(0, 0, 255))

        diff_mask = (out != image).any(axis=-1)
        changed = out[diff_mask]
        blue_pixels = (
            (changed[:, 0] < 60) & (changed[:, 1] < 60) & (changed[:, 2] > 200)
        ).sum()
        assert blue_pixels > 0


class TestRenderTextPlacement:
    def test_detection_against_top_edge_renders_without_negative_y(self):
        # Polygon touches y=0; without the fallback that places the
        # label below the bbox, putText would receive a negative y.
        image = _full(255)
        result = _make_result(
            image,
            polygon=(
                (10.0, 0.0),
                (60.0, 0.0),
                (60.0, 12.0),
                (10.0, 12.0),
            ),
        )

        out = render(result)

        assert out.shape == image.shape
        diff = (out != image).any(axis=-1)
        assert int(diff.sum()) > 0


class TestRenderMultipleDetections:
    def test_each_detection_contributes_a_box_to_the_output(self):
        image = _full(255)
        det_a = Detection(
            polygon=(
                (5.0, 5.0),
                (25.0, 5.0),
                (25.0, 15.0),
                (5.0, 15.0),
            ),
            confidence=0.9,
            scale=1.0,
            rotation=0.0,
        )
        det_b = Detection(
            polygon=(
                (100.0, 60.0),
                (140.0, 60.0),
                (140.0, 80.0),
                (100.0, 80.0),
            ),
            confidence=0.7,
            scale=1.5,
            rotation=0.0,
        )
        query: NDArray[np.uint8] = np.zeros((4, 4, 3), dtype=np.uint8)
        result = DetectResult(
            screenshot=_make_screenshot(image),
            query=query,
            detections=(det_a, det_b),
        )

        out = render(result)
        diff = (out != image).any(axis=-1)

        assert int(diff[5:16, 5:26].sum()) > 0
        assert int(diff[60:81, 100:141].sum()) > 0
