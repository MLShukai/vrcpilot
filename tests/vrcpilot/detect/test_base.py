"""Unit tests for :mod:`vrcpilot.detect.base`.

Covers the value-object contract of :class:`Detection`: polygon
length guard plus the derived geometry properties (``bbox`` /
``center``) that downstream callers (mouse.move, visualize.render)
depend on.
"""

from __future__ import annotations

from typing import cast

import pytest

from vrcpilot.detect import Detection
from vrcpilot.types import Polygon


def _detection(
    polygon: Polygon,
    confidence: float = 0.9,
    scale: float = 1.0,
    rotation: float = 0.0,
) -> Detection:
    return Detection(
        polygon=polygon,
        confidence=confidence,
        scale=scale,
        rotation=rotation,
    )


class TestDetectionPolygonValidation:
    @pytest.mark.parametrize(
        "bad_polygon",
        [
            (),
            ((0.0, 0.0),),
            ((0.0, 0.0), (1.0, 0.0)),
            ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
            (
                (0.0, 0.0),
                (1.0, 0.0),
                (1.0, 1.0),
                (0.0, 1.0),
                (0.5, 0.5),
            ),
        ],
    )
    def test_detection_rejects_polygon_with_wrong_vertex_count(
        self,
        bad_polygon: tuple[tuple[float, float], ...],
    ):
        # Static typing pins length=4 but dynamic tuple-building can
        # slip past the type checker; the dataclass must still reject.
        with pytest.raises(ValueError, match="must have exactly 4 points"):
            Detection(
                polygon=cast(Polygon, bad_polygon),
                confidence=0.5,
                scale=1.0,
                rotation=0.0,
            )


class TestDetectionBbox:
    def test_axis_aligned_polygon_yields_envelope_as_bbox(self):
        polygon: Polygon = (
            (10.0, 20.0),
            (60.0, 20.0),
            (60.0, 38.0),
            (10.0, 38.0),
        )
        assert _detection(polygon).bbox == (10, 20, 50, 18)

    def test_rotated_polygon_uses_axis_aligned_envelope(self):
        # Tilted quad: x in [2, 18], y in [3, 17].
        polygon: Polygon = (
            (10.0, 3.0),
            (18.0, 10.0),
            (10.0, 17.0),
            (2.0, 10.0),
        )
        assert _detection(polygon).bbox == (2, 3, 16, 14)

    def test_fractional_coordinates_round_to_nearest_int(self):
        polygon: Polygon = (
            (10.4, 20.4),
            (60.6, 20.4),
            (60.6, 38.6),
            (10.4, 38.6),
        )
        assert _detection(polygon).bbox == (10, 20, 50, 18)

    def test_degenerate_polygon_has_zero_width_and_height(self):
        polygon: Polygon = (
            (5.0, 7.0),
            (5.0, 7.0),
            (5.0, 7.0),
            (5.0, 7.0),
        )
        assert _detection(polygon).bbox == (5, 7, 0, 0)


class TestDetectionCenter:
    def test_axis_aligned_center_is_polygon_centroid(self):
        polygon: Polygon = (
            (10.0, 20.0),
            (60.0, 20.0),
            (60.0, 38.0),
            (10.0, 38.0),
        )
        cx, cy = _detection(polygon).center
        assert (cx, cy) == (35.0, 29.0)

    def test_center_is_returned_as_floats(self):
        polygon: Polygon = (
            (10.0, 20.0),
            (60.0, 20.0),
            (60.0, 38.0),
            (10.0, 38.0),
        )
        cx, cy = _detection(polygon).center
        assert isinstance(cx, float)
        assert isinstance(cy, float)

    def test_tilted_polygon_center_is_vertex_mean(self):
        polygon: Polygon = (
            (10.0, 3.0),
            (18.0, 10.0),
            (10.0, 17.0),
            (2.0, 10.0),
        )
        cx, cy = _detection(polygon).center
        assert cx == pytest.approx(10.0)
        assert cy == pytest.approx(10.0)
