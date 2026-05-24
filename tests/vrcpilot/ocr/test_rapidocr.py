"""Integration-real tests for :class:`vrcpilot.ocr.rapidocr.RapidOCREngine`.

Exercises the real rapidocr (PP-OCRv4 onnx) backend. The first run
downloads ~15 MB of model weights into the venv ``rapidocr/models/``
cache; subsequent runs reuse it. The full suite is module-level
skipped when the ``[ocr]`` extra is missing so plain ``just test``
on a minimal install still passes.
"""

from __future__ import annotations

from importlib.util import find_spec

import pytest

if find_spec("rapidocr") is None or find_spec("onnxruntime") is None:
    pytest.skip(
        "rapidocr/onnxruntime not installed; install with [ocr] extra",
        allow_module_level=True,
    )

import numpy as np  # noqa: E402
from numpy.typing import NDArray  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from vrcpilot.ocr import OCRWord, RapidOCREngine  # noqa: E402


def _hello_image() -> NDArray[np.uint8]:
    """Render the literal text ``Hello`` onto a 320x80 white RGB canvas."""
    img = Image.new("RGB", (320, 80), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # PIL default font is small; draw four times with 1-px offsets so
    # the strokes are thick enough for rapidocr to lock onto.
    text = "Hello"
    for ox, oy in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        draw.text((30 + ox, 20 + oy), text, fill=(0, 0, 0))
    return np.asarray(img, dtype=np.uint8)


class TestRapidOCREngineHappyPath:
    def test_recognizes_hello_text_in_synthetic_image(self):
        engine = RapidOCREngine()

        words = engine.recognize(_hello_image())

        assert len(words) >= 1
        joined = " ".join(w.text for w in words).lower()
        assert "hello" in joined

    def test_returns_ocrword_instances(self):
        engine = RapidOCREngine()

        words = engine.recognize(_hello_image())

        assert all(isinstance(w, OCRWord) for w in words)

    def test_clean_text_yields_at_least_one_confident_detection(self):
        engine = RapidOCREngine()

        words = engine.recognize(_hello_image())

        # Clean black-on-white synthetic text should clear the
        # confidence midpoint comfortably.
        assert max(w.confidence for w in words) > 0.5

    def test_all_bboxes_lie_inside_image_bounds(self):
        engine = RapidOCREngine()

        words = engine.recognize(_hello_image())

        for w in words:
            x, y, bw, bh = w.bbox
            assert 0 <= x <= 320
            assert 0 <= y <= 80
            assert bw >= 0
            assert bh >= 0
            # Allow 1-pixel slack for rounding at the right/bottom edge.
            assert x + bw <= 320 + 1
            assert y + bh <= 80 + 1


class TestRapidOCREngineEmpty:
    def test_blank_image_returns_empty_word_list(self):
        engine = RapidOCREngine()
        blank: NDArray[np.uint8] = np.full((100, 100, 3), 255, dtype=np.uint8)

        words = engine.recognize(blank)

        assert words == []
