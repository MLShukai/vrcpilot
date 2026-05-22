"""Tests for :mod:`vrcpilot.ocr.recognize`.

Integration-with-fakes: :func:`ocr` is exercised against the in-memory
:class:`tests.fakes.ocr.FakeOCREngine`, so no rapidocr model download
is triggered. The function itself takes a :class:`Screenshot`
directly, so capture is no longer mocked here.

The submodule reference is fetched via ``sys.modules`` because the
top-level package re-exports the ``ocr`` *function* as
``vrcpilot.ocr``, which shadows the submodule attribute on the
``vrcpilot`` package. Submodule access via ``sys.modules`` is the
unaffected path; see ``tests/vrcpilot/test_init.py`` for the
regression that pins this invariant.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from types import ModuleType

import numpy as np
import pytest
from numpy.typing import NDArray

import vrcpilot.ocr  # noqa: F401  ensures submodule is registered
from tests.fakes.ocr import FakeOCREngine
from vrcpilot.ocr import OCRResult, OCRWord, Polygon, ocr
from vrcpilot.screenshot import Screenshot

_recognize_module: ModuleType = sys.modules["vrcpilot.ocr.recognize"]


def _make_screenshot(
    *,
    x: int = 100,
    y: int = 50,
    width: int = 320,
    height: int = 200,
) -> Screenshot:
    image: NDArray[np.uint8] = np.zeros((height, width, 3), dtype=np.uint8)
    return Screenshot(
        image=image,
        x=x,
        y=y,
        width=width,
        height=height,
        monitor_index=1,
        captured_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc),
    )


def _make_word(
    polygon: Polygon = (
        (10.0, 20.0),
        (60.0, 20.0),
        (60.0, 38.0),
        (10.0, 38.0),
    ),
    text: str = "Hello",
    confidence: float = 0.97,
) -> OCRWord:
    return OCRWord(text=text, polygon=polygon, confidence=confidence)


@pytest.fixture(autouse=True)
def _reset_default_engine() -> Iterator[None]:
    """Reset module-level cache between tests so order is irrelevant."""
    _recognize_module._default_engine = None
    yield
    _recognize_module._default_engine = None


class TestOcrWithExplicitEngine:
    def test_returns_ocr_result_with_tuple_words(self):
        shot = _make_screenshot()
        word = _make_word()
        engine = FakeOCREngine([word])

        result = ocr(shot, engine=engine)

        assert isinstance(result, OCRResult)
        assert result.screenshot is shot
        assert isinstance(result.words, tuple)
        assert result.words == (word,)
        assert engine.calls == 1

    def test_engine_receives_image(self):
        shot = _make_screenshot()
        engine = FakeOCREngine([])

        ocr(shot, engine=engine)

        assert engine.calls == 1
        assert engine.last_image is shot.image

    def test_screenshot_passed_positionally(self):
        shot = _make_screenshot()
        engine = FakeOCREngine([])

        result = ocr(shot, engine=engine)

        assert result.screenshot is shot


class TestOcrDefaultEngineCache:
    def test_default_engine_is_built_once(self, monkeypatch: pytest.MonkeyPatch):
        shot = _make_screenshot()
        word = _make_word()
        build_count = {"n": 0}

        def _factory() -> FakeOCREngine:
            build_count["n"] += 1
            return FakeOCREngine([word])

        # Patch the RapidOCREngine reference inside the recognize
        # submodule so the default-engine path uses our fake.
        monkeypatch.setattr(_recognize_module, "RapidOCREngine", _factory)

        first = ocr(shot)
        second = ocr(shot)

        assert isinstance(first, OCRResult)
        assert isinstance(second, OCRResult)
        assert build_count["n"] == 1
        cached = _recognize_module._default_engine
        assert cached is not None
        assert isinstance(cached, FakeOCREngine)
        assert cached.calls == 2

    def test_resetting_cache_rebuilds_engine(self, monkeypatch: pytest.MonkeyPatch):
        shot = _make_screenshot()
        build_count = {"n": 0}

        def _factory() -> FakeOCREngine:
            build_count["n"] += 1
            return FakeOCREngine([])

        monkeypatch.setattr(_recognize_module, "RapidOCREngine", _factory)

        ocr(shot)
        assert build_count["n"] == 1

        _recognize_module._default_engine = None
        ocr(shot)
        assert build_count["n"] == 2
