"""Tests for :mod:`vrcpilot.cli.detect`.

``vrcpilot detect`` reads a :class:`Screenshot` (via ``--screenshot``
or piped stdin), runs the template-detection engine against a query
PNG, and writes a YAML payload to stdout. Same screenshot input
contract as :mod:`vrcpilot.cli.ocr`; the engine itself is swapped to
:class:`FakeDetectEngine` (a fake of the project-owned
:class:`vrcpilot.detect.DetectEngine` ABC) by setting
``_detect_module._default_engine`` directly.

The query-image side runs against a real on-disk PNG via OpenCV --
that part of the pipeline executes end-to-end.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image
from pytest_mock import MockerFixture

from tests.fakes import patch_stdin_with_screenshot, write_screenshot_payload
from tests.fakes.detect import FakeDetectEngine
from vrcpilot.cli import build_parser, main
from vrcpilot.cli.detect import _VIZ_DEFAULT, _resolve_viz_path
from vrcpilot.detect import Detection

# ``vrcpilot.detect.detect`` resolves to the re-exported *function* via
# ``from .detect import detect`` in ``vrcpilot/detect/__init__.py``; the
# attribute shadowing makes ``import vrcpilot.detect.detect`` (and
# ``vrcpilot.detect.detect`` attribute access) reach the function rather
# than the submodule. ``importlib.import_module`` bypasses the shadow
# and hands us the live module object whose ``_default_engine`` slot we
# need to swap.
_detect_module = importlib.import_module("vrcpilot.detect.detect")


def _make_detection(
    polygon: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ] = ((10.0, 20.0), (50.0, 20.0), (50.0, 60.0), (10.0, 60.0)),
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


def _write_query_png(target: Path, *, width: int = 16, height: int = 16) -> None:
    """Write a real, OpenCV-readable PNG to ``target``."""
    Image.fromarray(np.zeros((height, width, 3), dtype=np.uint8)).save(target)


@pytest.fixture
def fake_engine() -> Iterator[FakeDetectEngine]:
    """Swap the cached DetectEngine for a :class:`FakeDetectEngine`.

    The detect module documents ``_default_engine = None`` as the
    test-side reset seam; assigning a fake here exercises the same
    seam. The original value is restored on teardown.
    """
    engine = FakeDetectEngine([_make_detection()])
    original = _detect_module._default_engine  # noqa: SLF001
    _detect_module._default_engine = engine  # noqa: SLF001
    try:
        yield engine
    finally:
        _detect_module._default_engine = original  # noqa: SLF001


# ---------------------------------------------------------------------------
# Argparse plumbing
# ---------------------------------------------------------------------------


class TestDetectArgparse:
    def test_query_flag_required(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        with pytest.raises(SystemExit) as excinfo:
            main(["detect"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_query_short_form(self, tmp_path: Path):
        query = tmp_path / "q.png"
        ns = build_parser().parse_args(["detect", "-q", str(query)])
        assert ns.query == query

    def test_query_long_form(self, tmp_path: Path):
        query = tmp_path / "q.png"
        ns = build_parser().parse_args(["detect", "--query", str(query)])
        assert ns.query == query

    def test_threshold_optional(self, tmp_path: Path):
        query = tmp_path / "q.png"
        ns = build_parser().parse_args(
            ["detect", "-q", str(query), "--threshold", "0.7"]
        )
        assert ns.threshold == pytest.approx(0.7)

    def test_top_k_optional(self, tmp_path: Path):
        query = tmp_path / "q.png"
        ns = build_parser().parse_args(["detect", "-q", str(query), "--top-k", "5"])
        assert ns.top_k == 5

    def test_viz_absent_is_none(self, tmp_path: Path):
        query = tmp_path / "q.png"
        ns = build_parser().parse_args(["detect", "-q", str(query)])
        assert ns.viz is None

    def test_viz_without_arg_is_sentinel(self, tmp_path: Path):
        query = tmp_path / "q.png"
        ns = build_parser().parse_args(["detect", "-q", str(query), "--viz"])
        assert ns.viz is _VIZ_DEFAULT


class TestResolveVizPath:
    """Unit tests for the detect-side timestamp resolver."""

    def test_none_returns_none(self):
        now = datetime(2026, 5, 3, 12, 34, 56)
        assert _resolve_viz_path(None, now=now) is None

    def test_sentinel_returns_cwd_with_timestamp(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        now = datetime(2026, 5, 3, 12, 34, 56)
        resolved = _resolve_viz_path(_VIZ_DEFAULT, now=now)
        assert resolved == tmp_path / "vrcpilot_detect_viz_20260503_123456.png"

    def test_directory_path_returns_dir_with_timestamp(self, tmp_path: Path):
        now = datetime(2026, 5, 3, 12, 34, 56)
        resolved = _resolve_viz_path(tmp_path, now=now)
        assert resolved == tmp_path / "vrcpilot_detect_viz_20260503_123456.png"

    def test_file_path_returned_as_is(self, tmp_path: Path):
        target = tmp_path / "custom.png"
        now = datetime(2026, 5, 3, 12, 34, 56)
        assert _resolve_viz_path(target, now=now) == target


# ---------------------------------------------------------------------------
# Screenshot input + query image resolution
# ---------------------------------------------------------------------------


class TestDetectInputResolution:
    def test_no_screenshot_source_exits_1(
        self,
        fake_engine: FakeDetectEngine,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        query = tmp_path / "q.png"
        _write_query_png(query)

        # Autouse pins isatty()=True, no --screenshot flag.
        assert main(["detect", "-q", str(query)]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: no screenshot provided" in captured.err

    def test_missing_query_file_exits_1(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        missing = tmp_path / "does-not-exist.png"

        assert main(["detect", "-q", str(missing)]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: could not read query image" in captured.err

    def test_screenshot_flag_loads_yaml(
        self,
        fake_engine: FakeDetectEngine,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        yaml_path, yaml_text = write_screenshot_payload(tmp_path)
        yaml_path.write_text(yaml_text)
        query = tmp_path / "q.png"
        _write_query_png(query)

        assert main(["detect", "-q", str(query), "--screenshot", str(yaml_path)]) == 0

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "captured_at" in loaded
        assert "window" in loaded
        assert "query" in loaded
        assert "detections" in loaded

    def test_stdin_loads_yaml(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        query = tmp_path / "q.png"
        _write_query_png(query)

        assert main(["detect", "-q", str(query)]) == 0

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "captured_at" in loaded
        assert "detections" in loaded


# ---------------------------------------------------------------------------
# YAML payload shape (success path)
# ---------------------------------------------------------------------------


class TestDetectYamlPayload:
    def test_top_level_keys(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        query = tmp_path / "q.png"
        _write_query_png(query, width=24, height=16)

        main(["detect", "-q", str(query)])

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert list(loaded.keys()) == [
            "captured_at",
            "window",
            "query",
            "detections",
        ]

    def test_window_key_order(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        query = tmp_path / "q.png"
        _write_query_png(query)

        main(["detect", "-q", str(query)])

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert list(loaded["window"].keys()) == [
            "x",
            "y",
            "width",
            "height",
            "monitor_index",
        ]

    def test_query_metadata_matches_file(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        query = tmp_path / "q.png"
        _write_query_png(query, width=24, height=16)

        main(["detect", "-q", str(query)])

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["query"]["path"]) == query.resolve()
        assert loaded["query"]["width"] == 24
        assert loaded["query"]["height"] == 16

    def test_detection_key_order_and_pos_shape(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        query = tmp_path / "q.png"
        _write_query_png(query)

        main(["detect", "-q", str(query)])

        loaded = yaml.safe_load(capsys.readouterr().out)
        det = loaded["detections"][0]
        assert list(det.keys()) == ["confidence", "scale", "rotation", "pos"]
        assert list(det["pos"].keys()) == ["polygon", "bbox"]

    def test_detection_values_match_engine_output(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        query = tmp_path / "q.png"
        _write_query_png(query)

        main(["detect", "-q", str(query)])

        loaded = yaml.safe_load(capsys.readouterr().out)
        det = loaded["detections"][0]
        assert det["confidence"] == pytest.approx(0.9)
        assert det["scale"] == pytest.approx(1.0)
        assert det["rotation"] == pytest.approx(0.0)
        assert det["pos"]["polygon"] == [
            [10, 20],
            [50, 20],
            [50, 60],
            [10, 60],
        ]
        assert det["pos"]["bbox"] == [10, 20, 40, 40]


# ---------------------------------------------------------------------------
# --top-k filtering
# ---------------------------------------------------------------------------


class TestDetectTopK:
    def test_top_k_limits_output(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        # Stage three detections with distinct confidences; --top-k 2
        # should keep the highest two in descending order.
        engine = FakeDetectEngine(
            [
                _make_detection(confidence=0.5),
                _make_detection(confidence=0.9),
                _make_detection(confidence=0.7),
            ]
        )
        original = _detect_module._default_engine  # noqa: SLF001
        _detect_module._default_engine = engine  # noqa: SLF001
        try:
            patch_stdin_with_screenshot(mocker, tmp_path)
            query = tmp_path / "q.png"
            _write_query_png(query)

            assert main(["detect", "-q", str(query), "--top-k", "2"]) == 0

            loaded = yaml.safe_load(capsys.readouterr().out)
            confidences = [d["confidence"] for d in loaded["detections"]]
            assert confidences == [pytest.approx(0.9), pytest.approx(0.7)]
        finally:
            _detect_module._default_engine = original  # noqa: SLF001


# ---------------------------------------------------------------------------
# --viz: PNG output + viz_path field
# ---------------------------------------------------------------------------


class TestDetectViz:
    def test_no_viz_writes_no_png(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        monkeypatch.chdir(tmp_path)
        query = tmp_path / "q.png"
        _write_query_png(query)

        assert main(["detect", "-q", str(query)]) == 0

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "viz_path" not in loaded
        assert list(tmp_path.glob("vrcpilot_detect_viz_*.png")) == []

    def test_viz_no_arg_writes_to_cwd(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        monkeypatch.chdir(tmp_path)
        query = tmp_path / "q.png"
        _write_query_png(query)

        assert main(["detect", "-q", str(query), "--viz"]) == 0

        produced = list(tmp_path.glob("vrcpilot_detect_viz_*.png"))
        assert len(produced) == 1
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["viz_path"]) == produced[0].resolve()

    def test_viz_with_explicit_file_path(
        self,
        fake_engine: FakeDetectEngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        query = tmp_path / "q.png"
        _write_query_png(query)
        target = tmp_path / "custom.png"

        assert main(["detect", "-q", str(query), "--viz", str(target)]) == 0

        assert target.is_file()
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["viz_path"]) == target.resolve()
