"""Tests for :mod:`vrcpilot.ocr.visualize`.

Integration-real with the real OpenCV (cv2.polylines / putText /
getTextSize) drawing primitives. The function under test is a pure
ndarray -> ndarray transform, so verification is done by inspecting
the rendered canvas: shape, dtype, immutability of the source, and
which pixel colours appear in the diff against the input.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from numpy.typing import NDArray

from vrcpilot.ocr import OCRResult, OCRWord, Polygon, render
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
        captured_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
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
    text: str = "Hi",
) -> OCRResult:
    word = OCRWord(text=text, polygon=polygon, confidence=0.9)
    return OCRResult(screenshot=_make_screenshot(image), words=(word,))


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
        image = _full(128)
        shot = _make_screenshot(image)
        result = OCRResult(screenshot=shot, words=())

        out = render(result)

        # Empty word list still returns a new array (documented
        # "screenshot is never mutated" contract).
        assert out is not image


class TestRenderDrawsForEachWord:
    def test_non_empty_words_produce_pixel_diff(self):
        image = _full(255)
        result = _make_result(image)

        out = render(result)

        diff = (out != image).any(axis=-1)
        assert int(diff.sum()) > 0

    def test_empty_words_returns_canvas_unchanged(self):
        # Documented: "screenshot is never mutated"; with no words the
        # canvas is a faithful copy of the source pixels.
        image = _full(128)
        shot = _make_screenshot(image)
        result = OCRResult(screenshot=shot, words=())

        out = render(result)

        assert np.array_equal(out, image)


class TestRenderAutoContrastTextColor:
    def test_white_background_draws_dark_text_for_legibility(self):
        image = _full(255)
        result = _make_result(image)

        out = render(result)

        diff_mask = (out != image).any(axis=-1)
        changed = out[diff_mask]
        # White bg + green box (0,255,0) + black text: at least one
        # changed pixel must be near-black (sum < 60).
        near_black = (changed.sum(axis=-1) < 60).sum()
        assert near_black > 0

    def test_black_background_draws_light_text_for_legibility(self):
        image = _full(0)
        result = _make_result(image)

        out = render(result)

        diff_mask = (out != image).any(axis=-1)
        changed = out[diff_mask]
        # Black bg + green box (0,255,0) + white text: at least one
        # changed pixel must be near-white (sum > 700).
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
    def test_word_against_top_edge_renders_without_negative_y(self):
        # Polygon touches y=0; without the fallback that places text
        # below the bbox, putText would receive a negative y and either
        # crash or draw outside the canvas. The render must complete
        # and produce visible pixels inside the canvas.
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


class TestRenderMultipleWords:
    def test_each_word_contributes_a_box_to_the_output(self):
        # Two non-overlapping words at different positions should each
        # leave a green-box footprint; the diff against the source must
        # span both bbox regions.
        image = _full(255)
        word_a = OCRWord(
            text="A",
            polygon=(
                (5.0, 5.0),
                (25.0, 5.0),
                (25.0, 15.0),
                (5.0, 15.0),
            ),
            confidence=0.9,
        )
        word_b = OCRWord(
            text="B",
            polygon=(
                (100.0, 60.0),
                (140.0, 60.0),
                (140.0, 80.0),
                (100.0, 80.0),
            ),
            confidence=0.9,
        )
        result = OCRResult(screenshot=_make_screenshot(image), words=(word_a, word_b))

        out = render(result)
        diff = (out != image).any(axis=-1)

        # Pixels were changed near both word polygon footprints.
        assert int(diff[5:16, 5:26].sum()) > 0
        assert int(diff[60:81, 100:141].sum()) > 0
