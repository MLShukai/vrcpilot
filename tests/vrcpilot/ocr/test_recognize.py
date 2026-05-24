"""Tests for :mod:`vrcpilot.ocr.recognize`.

Integration-with-fakes: :func:`ocr` is exercised against
:class:`tests.fakes.ocr.FakeOCREngine` (an in-memory implementation
of the :class:`vrcpilot.ocr.OCREngine` ABC), so no rapidocr model
download is triggered. Capture is the caller's responsibility, so the
test passes a hand-built :class:`Screenshot` directly.

The recognize submodule is accessed via ``sys.modules`` because the
top-level package re-exports the ``ocr`` *function* as
``vrcpilot.ocr``, which shadows the submodule attribute. The
``sys.modules`` lookup is the unaffected path; see
``tests/vrcpilot/test_init.py`` for the regression that pins this.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from types import ModuleType

import numpy as np
import pytest
from numpy.typing import NDArray

import vrcpilot.ocr  # noqa: F401 — ensures submodule is registered
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
    """Reset the module-level default engine cache between tests.

    The cache is process-wide by design, so without this reset test
    order would leak engine instances between cases.
    """
    _recognize_module._default_engine = None
    yield
    _recognize_module._default_engine = None


class TestOcrWithExplicitEngine:
    def test_ocr_returns_OCRResult_wrapping_the_input_screenshot(self):
        shot = _make_screenshot()
        engine = FakeOCREngine([_make_word()])

        result = ocr(shot, engine=engine)

        assert isinstance(result, OCRResult)
        assert result.screenshot is shot

    def test_words_are_returned_as_immutable_tuple(self):
        shot = _make_screenshot()
        word = _make_word()
        engine = FakeOCREngine([word])

        result = ocr(shot, engine=engine)

        assert isinstance(result.words, tuple)
        assert result.words == (word,)

    def test_engine_recognize_is_called_with_screenshot_image(self):
        shot = _make_screenshot()
        engine = FakeOCREngine([])

        ocr(shot, engine=engine)

        assert engine.calls == 1
        assert engine.last_image is shot.image

    def test_each_ocr_call_invokes_engine_once(self):
        shot = _make_screenshot()
        engine = FakeOCREngine([_make_word()])

        ocr(shot, engine=engine)
        ocr(shot, engine=engine)
        ocr(shot, engine=engine)

        assert engine.calls == 3


class TestOcrDefaultEngineCache:
    def test_default_engine_is_built_once_across_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # The default engine is the cached process-wide RapidOCREngine.
        # We swap the class reference in the recognize module with a
        # factory that records construction counts; the factory still
        # returns an own-ABC implementation (FakeOCREngine).
        shot = _make_screenshot()
        build_count = {"n": 0}

        def _factory() -> FakeOCREngine:
            build_count["n"] += 1
            return FakeOCREngine([_make_word()])

        monkeypatch.setattr(_recognize_module, "RapidOCREngine", _factory)

        ocr(shot)
        ocr(shot)
        ocr(shot)

        assert build_count["n"] == 1

    def test_cached_engine_serves_subsequent_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        shot = _make_screenshot()
        monkeypatch.setattr(
            _recognize_module,
            "RapidOCREngine",
            lambda: FakeOCREngine([_make_word()]),
        )

        ocr(shot)
        ocr(shot)

        cached = _recognize_module._default_engine
        assert isinstance(cached, FakeOCREngine)
        assert cached.calls == 2

    def test_resetting_cache_to_none_rebuilds_engine_on_next_call(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # Documented escape hatch: tests can null out the cache to
        # force a rebuild. This is the contract test for that.
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
