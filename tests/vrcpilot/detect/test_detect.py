"""Tests for :mod:`vrcpilot.detect.detect`.

Integration-with-fakes: :func:`detect` is exercised against
:class:`tests.fakes.detect.FakeDetectEngine` (an in-memory
implementation of the :class:`vrcpilot.detect.DetectEngine` ABC), so
no real OpenCV matching is run. The function itself takes a
:class:`Screenshot` directly, so capture is not exercised here.

The detect submodule is accessed via ``sys.modules`` because the
package binds the ``detect`` *function* under ``vrcpilot.detect.detect``
which would otherwise shadow the submodule in attribute-walking
patch helpers.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from types import ModuleType

import numpy as np
import pytest
from numpy.typing import NDArray

import vrcpilot.detect  # noqa: F401 — ensures submodule is registered
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
    """Reset the module-level default engine cache between tests.

    The cache is process-wide by design, so without this reset test
    order would leak engine instances between cases.
    """
    _detect_module._default_engine = None
    yield
    _detect_module._default_engine = None


class TestDetectWithExplicitEngine:
    def test_detect_returns_DetectResult_wrapping_the_input_screenshot(self):
        shot = _make_screenshot()
        query = _make_query()
        engine = FakeDetectEngine([_make_detection()])

        result = detect(shot, query, engine=engine)

        assert isinstance(result, DetectResult)
        assert result.screenshot is shot

    def test_detect_preserves_the_query_reference_on_the_result(self):
        # The query ndarray is stored by reference (engines do not
        # mutate); callers can therefore inspect what was searched for.
        shot = _make_screenshot()
        query = _make_query()
        engine = FakeDetectEngine([])

        result = detect(shot, query, engine=engine)

        assert result.query is query

    def test_detections_are_returned_as_immutable_tuple(self):
        shot = _make_screenshot()
        query = _make_query()
        det = _make_detection()
        engine = FakeDetectEngine([det])

        result = detect(shot, query, engine=engine)

        assert isinstance(result.detections, tuple)
        assert result.detections == (det,)

    def test_engine_detect_is_called_with_screenshot_image_and_query(self):
        shot = _make_screenshot()
        query = _make_query()
        engine = FakeDetectEngine([])

        detect(shot, query, engine=engine)

        assert engine.calls == 1
        assert engine.last_image is shot.image
        assert engine.last_query is query

    @pytest.mark.parametrize("count", [0, 1, 3])
    def test_detection_count_propagates_from_engine_output(self, count: int):
        shot = _make_screenshot()
        query = _make_query()
        dets = [_make_detection(confidence=0.9 - 0.1 * i) for i in range(count)]
        engine = FakeDetectEngine(dets)

        result = detect(shot, query, engine=engine)

        assert len(result.detections) == count
        assert result.detections == tuple(dets)


class TestDetectDefaultEngineCache:
    def test_default_engine_is_built_once_across_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # The default engine is the cached process-wide
        # TemplateDetectEngine. We swap the class reference in the
        # detect module with a factory that records construction
        # counts; the factory still returns an own-ABC implementation
        # (FakeDetectEngine).
        shot = _make_screenshot()
        query = _make_query()
        build_count = {"n": 0}

        def _factory() -> FakeDetectEngine:
            build_count["n"] += 1
            return FakeDetectEngine([_make_detection()])

        monkeypatch.setattr(_detect_module, "TemplateDetectEngine", _factory)

        detect(shot, query)
        detect(shot, query)
        detect(shot, query)

        assert build_count["n"] == 1

    def test_cached_engine_serves_subsequent_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        shot = _make_screenshot()
        query = _make_query()
        monkeypatch.setattr(
            _detect_module,
            "TemplateDetectEngine",
            lambda: FakeDetectEngine([_make_detection()]),
        )

        detect(shot, query)
        detect(shot, query)

        cached = _detect_module._default_engine
        assert isinstance(cached, FakeDetectEngine)
        assert cached.calls == 2

    def test_resetting_cache_to_none_rebuilds_engine_on_next_call(
        self, monkeypatch: pytest.MonkeyPatch
    ):
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
