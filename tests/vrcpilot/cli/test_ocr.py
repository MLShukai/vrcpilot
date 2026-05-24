"""Tests for :mod:`vrcpilot.cli.ocr`.

``vrcpilot ocr`` reads a :class:`Screenshot` (via ``--screenshot`` or
piped stdin), runs the OCR engine, and writes a YAML payload to stdout.
The CLI never captures a fresh screenshot on its own -- that pipeline
was removed -- so the screenshot side is fed end-to-end via real YAML
written by :func:`tests.fakes.write_screenshot_payload`.

The OCR engine itself is swapped to :class:`FakeOCREngine` (a fake of
the project-owned :class:`vrcpilot.ocr.OCREngine` ABC) by setting
``_ocr_module._default_engine`` directly. The module's
docstring documents this as the supported test seam, so the assignment
is part of the contract, not a private-state hack.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from pytest_mock import MockerFixture

from tests.fakes import patch_stdin_with_screenshot, write_screenshot_payload
from tests.fakes.ocr import FakeOCREngine
from vrcpilot.cli import build_parser, main
from vrcpilot.cli.ocr import _VIZ_DEFAULT, _resolve_viz_path
from vrcpilot.ocr import OCRWord

# ``vrcpilot.ocr.recognize`` is shadowed by a re-exported attribute on
# the parent package (``from .recognize import OCRResult, ocr`` makes
# ``vrcpilot.ocr.recognize`` resolve to a *function* rather than the
# module). Use ``importlib`` to fetch the real module object whose
# ``_default_engine`` slot needs to be swapped between tests.
_ocr_module = importlib.import_module("vrcpilot.ocr.recognize")


def _make_word(
    text: str = "Hello",
    polygon: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ] = ((10.0, 20.0), (60.0, 20.0), (60.0, 38.0), (10.0, 38.0)),
    confidence: float = 0.97,
) -> OCRWord:
    return OCRWord(text=text, polygon=polygon, confidence=confidence)


@pytest.fixture
def fake_engine() -> Iterator[FakeOCREngine]:
    """Swap the cached :class:`OCREngine` for a :class:`FakeOCREngine`.

    The OCR module's module docstring documents
    ``_default_engine = None`` as the way to reset the cache between
    tests; assigning a fake here exercises the same seam. The original
    value is restored on teardown so other tests keep observing the
    real default.
    """
    engine = FakeOCREngine([_make_word()])
    original = _ocr_module._default_engine  # noqa: SLF001
    _ocr_module._default_engine = engine  # noqa: SLF001
    try:
        yield engine
    finally:
        _ocr_module._default_engine = original  # noqa: SLF001


# ---------------------------------------------------------------------------
# Argparse plumbing
# ---------------------------------------------------------------------------


class TestOcrArgparse:
    def test_screenshot_flag_short(self, tmp_path: Path):
        yaml_path = tmp_path / "x.yaml"
        ns = build_parser().parse_args(["ocr", "-s", str(yaml_path)])
        assert ns.screenshot == yaml_path

    def test_screenshot_flag_long(self, tmp_path: Path):
        yaml_path = tmp_path / "x.yaml"
        ns = build_parser().parse_args(["ocr", "--screenshot", str(yaml_path)])
        assert ns.screenshot == yaml_path

    def test_screenshot_defaults_to_none(self):
        ns = build_parser().parse_args(["ocr"])
        assert ns.screenshot is None

    def test_viz_absent_is_none(self):
        ns = build_parser().parse_args(["ocr"])
        assert ns.viz is None

    def test_viz_without_arg_is_sentinel(self):
        ns = build_parser().parse_args(["ocr", "--viz"])
        # ``--viz`` with no path stores the documented sentinel; the
        # CLI's ``_resolve_viz_path`` later turns this into
        # ``cwd / vrcpilot_ocr_viz_<timestamp>.png``.
        assert ns.viz is _VIZ_DEFAULT

    def test_viz_with_path(self, tmp_path: Path):
        target = tmp_path / "viz.png"
        ns = build_parser().parse_args(["ocr", "--viz", str(target)])
        assert ns.viz == target


# ---------------------------------------------------------------------------
# _resolve_viz_path
# ---------------------------------------------------------------------------


class TestResolveVizPath:
    """Unit tests for the timestamp-aware viz-path resolver."""

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
        assert resolved == tmp_path / "vrcpilot_ocr_viz_20260503_123456.png"

    def test_directory_path_returns_dir_with_timestamp(self, tmp_path: Path):
        now = datetime(2026, 5, 3, 12, 34, 56)
        resolved = _resolve_viz_path(tmp_path, now=now)
        assert resolved == tmp_path / "vrcpilot_ocr_viz_20260503_123456.png"

    def test_file_path_returned_as_is(self, tmp_path: Path):
        target = tmp_path / "custom.png"
        now = datetime(2026, 5, 3, 12, 34, 56)
        assert _resolve_viz_path(target, now=now) == target


# ---------------------------------------------------------------------------
# Screenshot input resolution -- exit-1 / exit-0 paths
# ---------------------------------------------------------------------------


class TestOcrInputResolution:
    """``--screenshot`` and piped stdin are the only allowed inputs."""

    def test_screenshot_flag_loads_yaml(
        self,
        fake_engine: FakeOCREngine,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        yaml_path, yaml_text = write_screenshot_payload(tmp_path)
        yaml_path.write_text(yaml_text)

        assert main(["ocr", "--screenshot", str(yaml_path)]) == 0

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "captured_at" in loaded
        assert "window" in loaded
        assert "words" in loaded

    def test_stdin_loads_yaml(
        self,
        fake_engine: FakeOCREngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        # ``patch_stdin_with_screenshot`` swaps stdin for a StringIO
        # whose ``isatty()`` returns False natively, which is the piped-
        # stdin signal that ``resolve_screenshot`` looks for.
        patch_stdin_with_screenshot(mocker, tmp_path)

        assert main(["ocr"]) == 0

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "captured_at" in loaded
        assert "window" in loaded
        assert "words" in loaded

    def test_missing_screenshot_file_exits_1(
        self,
        fake_engine: FakeOCREngine,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        assert main(["ocr", "--screenshot", "/nonexistent/path.yaml"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: --screenshot file not found:" in captured.err

    def test_malformed_screenshot_yaml_exits_1(
        self,
        fake_engine: FakeOCREngine,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        # Valid YAML but not a mapping -> Screenshot.load raises
        # ValueError which the CLI maps to a single vrcpilot: line.
        broken = tmp_path / "broken.yaml"
        broken.write_text("- not\n- a\n- mapping\n")

        assert main(["ocr", "--screenshot", str(broken)]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_no_source_exits_1_with_guidance(
        self,
        fake_engine: FakeOCREngine,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        # Autouse pins isatty()=True, no --screenshot flag => "no
        # screenshot provided" guidance + exit 1.
        assert main(["ocr"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: no screenshot provided" in captured.err
        assert "--screenshot" in captured.err
        assert "stdin" in captured.err


# ---------------------------------------------------------------------------
# YAML payload shape (success path)
# ---------------------------------------------------------------------------


class TestOcrYamlPayload:
    def test_top_level_keys_no_viz(
        self,
        fake_engine: FakeOCREngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)

        assert main(["ocr"]) == 0

        loaded = yaml.safe_load(capsys.readouterr().out)
        # Key order matters: the CLI emits with sort_keys=False so
        # downstream YAML readers see a stable shape.
        assert list(loaded.keys()) == ["captured_at", "window", "words"]

    def test_window_key_order(
        self,
        fake_engine: FakeOCREngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)

        main(["ocr"])

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert list(loaded["window"].keys()) == [
            "x",
            "y",
            "width",
            "height",
            "monitor_index",
        ]

    def test_word_key_order_and_pos_shape(
        self,
        fake_engine: FakeOCREngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)

        main(["ocr"])

        loaded = yaml.safe_load(capsys.readouterr().out)
        word = loaded["words"][0]
        assert list(word.keys()) == ["text", "confidence", "pos"]
        assert list(word["pos"].keys()) == ["polygon", "bbox"]

    def test_word_values_match_engine_output(
        self,
        fake_engine: FakeOCREngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)

        main(["ocr"])

        loaded = yaml.safe_load(capsys.readouterr().out)
        word = loaded["words"][0]
        assert word["text"] == "Hello"
        assert word["confidence"] == pytest.approx(0.97)
        # The fake engine returns the canonical Hello polygon; bbox is
        # the axis-aligned envelope (x, y, w, h).
        assert word["pos"]["polygon"] == [
            [10, 20],
            [60, 20],
            [60, 38],
            [10, 38],
        ]
        assert word["pos"]["bbox"] == [10, 20, 50, 18]

    def test_window_values_match_input(
        self,
        fake_engine: FakeOCREngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        # ``patch_stdin_with_screenshot`` uses width=64, height=48,
        # x=100, y=50 by default.
        patch_stdin_with_screenshot(mocker, tmp_path)

        main(["ocr"])

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert loaded["window"] == {
            "x": 100,
            "y": 50,
            "width": 64,
            "height": 48,
            "monitor_index": 1,
        }


# ---------------------------------------------------------------------------
# --viz: PNG output + viz_path field
# ---------------------------------------------------------------------------


class TestOcrViz:
    def test_no_viz_writes_no_png(
        self,
        fake_engine: FakeOCREngine,
        mocker: MockerFixture,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        monkeypatch.chdir(tmp_path)

        assert main(["ocr"]) == 0

        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "viz_path" not in loaded
        # The fixture writes ``screenshot.png`` as a side effect; we
        # only care that no ``vrcpilot_ocr_viz_*`` PNG was produced.
        assert list(tmp_path.glob("vrcpilot_ocr_viz_*.png")) == []

    def test_viz_no_arg_writes_to_cwd(
        self,
        fake_engine: FakeOCREngine,
        mocker: MockerFixture,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        monkeypatch.chdir(tmp_path)

        assert main(["ocr", "--viz"]) == 0

        produced = list(tmp_path.glob("vrcpilot_ocr_viz_*.png"))
        assert len(produced) == 1
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["viz_path"]) == produced[0].resolve()

    def test_viz_with_explicit_file_path(
        self,
        fake_engine: FakeOCREngine,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_engine
        patch_stdin_with_screenshot(mocker, tmp_path)
        target = tmp_path / "custom.png"

        assert main(["ocr", "--viz", str(target)]) == 0

        assert target.is_file()
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["viz_path"]) == target.resolve()
