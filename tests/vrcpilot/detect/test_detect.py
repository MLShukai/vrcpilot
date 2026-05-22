"""Tests for :mod:`vrcpilot.detect.detect`.

Integration-with-fakes: :func:`detect` is exercised against the
in-memory :class:`tests.fakes.detect.FakeDetectEngine`, so no real
detection engine is built. The function itself takes a
:class:`Screenshot` directly, so capture is not mocked here.

The submodule reference is fetched via ``sys.modules`` because the
package binds the ``detect`` *function* under the name
``vrcpilot.detect.detect``, which would otherwise shadow the
submodule in attribute-walking patch helpers.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from types import ModuleType

import numpy as np
import pytest
from numpy.typing import NDArray

import vrcpilot.detect  # noqa: F401  ensures submodule is registered
from tests.fakes.detect import FakeDetectEngine
from vrcpilot.detect import Detection, DetectResult, Polygon, detect
from vrcpilot.screenshot import Screenshot

_detect_module: ModuleType = sys.modules["vrcpilot.detect.detect"]


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
        captured_at=datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc),
    )


def _make_query(*, height: int = 32, width: int = 48) -> NDArray[np.uint8]:
    return np.zeros((height, width, 3), dtype=np.uint8)


def _make_detection(
    polygon: Polygon = (
        (10.0, 20.0),
        (60.0, 20.0),
        (60.0, 38.0),
        (10.0, 38.0),
    ),
    confidence: float = 0.92,
    scale: float = 1.0,
    rotation: float = 0.0,
) -> Detection:
    return Detection(
        polygon=polygon,
        confidence=confidence,
        scale=scale,
        rotation=rotation,
    )


@pytest.fixture(autouse=True)
def _reset_default_engine() -> Iterator[None]:
    """Reset module-level cache between tests so order is irrelevant."""
    _detect_module._default_engine = None
    yield
    _detect_module._default_engine = None


class TestDetectWithExplicitEngine:
    def test_returns_detect_result_with_tuple_detections(self):
        shot = _make_screenshot()
        query = _make_query()
        det = _make_detection()
        engine = FakeDetectEngine([det])

        result = detect(shot, query, engine=engine)

        assert isinstance(result, DetectResult)
        assert result.screenshot is shot
        assert result.query is query
        assert isinstance(result.detections, tuple)
        assert result.detections == (det,)
        assert engine.calls == 1

    def test_engine_receives_image_and_query(self):
        shot = _make_screenshot()
        query = _make_query()
        engine = FakeDetectEngine([])

        detect(shot, query, engine=engine)

        assert engine.calls == 1
        assert engine.last_image is shot.image
        assert engine.last_query is query

    def test_screenshot_and_query_passed_positionally(self):
        shot = _make_screenshot()
        query = _make_query()
        engine = FakeDetectEngine([])

        result = detect(shot, query, engine=engine)

        assert result.screenshot is shot
        assert result.query is query

    @pytest.mark.parametrize("count", [0, 1, 3])
    def test_detection_count_matches_engine_output(self, count: int):
        shot = _make_screenshot()
        query = _make_query()
        dets = [_make_detection(confidence=0.9 - 0.1 * i) for i in range(count)]
        engine = FakeDetectEngine(dets)

        result = detect(shot, query, engine=engine)

        assert len(result.detections) == count
        assert result.detections == tuple(dets)


class TestDetectDefaultEngineCache:
    def test_default_engine_is_built_once(self, monkeypatch: pytest.MonkeyPatch):
        shot = _make_screenshot()
        query = _make_query()
        det = _make_detection()
        build_count = {"n": 0}

        def _factory() -> FakeDetectEngine:
            build_count["n"] += 1
            return FakeDetectEngine([det])

        # Patch the TemplateDetectEngine reference inside the detect
        # submodule so the default-engine path uses our fake.
        monkeypatch.setattr(_detect_module, "TemplateDetectEngine", _factory)

        first = detect(shot, query)
        second = detect(shot, query)

        assert isinstance(first, DetectResult)
        assert isinstance(second, DetectResult)
        assert build_count["n"] == 1
        cached = _detect_module._default_engine
        assert cached is not None
        assert isinstance(cached, FakeDetectEngine)
        assert cached.calls == 2

    def test_resetting_cache_rebuilds_engine(self, monkeypatch: pytest.MonkeyPatch):
        shot = _make_screenshot()
        query = _make_query()
        build_count = {"n": 0}

        def _factory() -> FakeDetectEngine:
            build_count["n"] += 1
            return FakeDetectEngine([])

        monkeypatch.setattr(_detect_module, "TemplateDetectEngine", _factory)

        detect(shot, query)
        assert build_count["n"] == 1

        _detect_module._default_engine = None
        detect(shot, query)
        assert build_count["n"] == 2
