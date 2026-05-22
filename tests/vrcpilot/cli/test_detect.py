"""Tests for :mod:`vrcpilot.cli.detect`."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
import pytest
import yaml
from numpy.typing import NDArray
from pytest_mock import MockerFixture

import vrcpilot.detect  # noqa: F401  ensures submodule is registered
from tests.fakes import patch_stdin_with_screenshot, write_screenshot_payload
from tests.fakes.detect import FakeDetectEngine
from vrcpilot.cli import main
from vrcpilot.cli.detect import _VIZ_DEFAULT, _resolve_viz_path
from vrcpilot.detect import Detection
from vrcpilot.screenshot import Screenshot

_detect_module: ModuleType = sys.modules["vrcpilot.detect.detect"]


def _make_screenshot(
    *,
    width: int = 320,
    height: int = 200,
    x: int = 100,
    y: int = 50,
    monitor_index: int = 1,
    captured_at: datetime | None = None,
) -> Screenshot:
    if captured_at is None:
        captured_at = datetime(2026, 5, 5, 12, 34, 56, 789012, tzinfo=timezone.utc)
    return Screenshot(
        image=np.zeros((height, width, 3), dtype=np.uint8),
        x=x,
        y=y,
        width=width,
        height=height,
        monitor_index=monitor_index,
        captured_at=captured_at,
    )


def _make_detection(
    *,
    polygon: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ] = ((10.0, 20.0), (60.0, 20.0), (60.0, 38.0), (10.0, 38.0)),
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


def _write_query_png(path: Path, *, width: int = 48, height: int = 32) -> None:
    """Write a real PNG so :func:`cv2.imread` can decode it."""
    image: NDArray[np.uint8] = np.full((height, width, 3), 200, dtype=np.uint8)
    # cv2.imwrite expects BGR; the source colours don't matter here.
    cv2.imwrite(str(path), image)


@pytest.fixture
def query_png(tmp_path: Path) -> Path:
    """Write a small PNG to ``tmp_path`` and return the path."""
    target = tmp_path / "query.png"
    _write_query_png(target, width=48, height=32)
    return target


@pytest.fixture
def patched_detect(mocker: MockerFixture, tmp_path: Path) -> Iterator[FakeDetectEngine]:
    """Feed a screenshot via piped stdin and inject a ``FakeDetectEngine``.

    Since commit 10 removed the live-capture fallback,
    :func:`vrcpilot.cli._common.resolve_screenshot` only honours
    ``--screenshot`` or piped stdin. This fixture takes the stdin path
    via :func:`patch_stdin_with_screenshot` so ``detect`` reads the YAML
    on demand. A :class:`FakeDetectEngine` with a single high-confidence
    detection is injected into the cached default engine slot of
    ``vrcpilot.detect.detect`` so the CLI's ``detect()`` call uses it
    without constructing a real TemplateDetectEngine.
    """
    detection = _make_detection()
    # Match the defaults assumed by tests in this module:
    # x=100, y=50, width=320, height=200, monitor_index=1, fixed
    # captured_at so ``test_captured_at_is_isoformat`` can compare.
    patch_stdin_with_screenshot(
        mocker,
        tmp_path,
        width=320,
        height=200,
        x=100,
        y=50,
        monitor_index=1,
        captured_at=datetime(2026, 5, 5, 12, 34, 56, 789012, tzinfo=timezone.utc),
    )
    engine = FakeDetectEngine([detection])
    _detect_module._default_engine = engine
    yield engine
    _detect_module._default_engine = None


@pytest.fixture
def patched_render(mocker: MockerFixture) -> None:
    """Patch the visualization boundary so unit tests skip the real cv2
    draw."""
    rendered = np.zeros((200, 320, 3), dtype=np.uint8)
    mocker.patch("vrcpilot.cli.detect.render", return_value=rendered)


class TestResolveVizPath:
    def test_none_returns_none(self):
        now = datetime(2026, 5, 5, 12, 34, 56)
        assert _resolve_viz_path(None, now=now) is None

    def test_sentinel_returns_cwd_with_timestamp(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        now = datetime(2026, 5, 5, 12, 34, 56)
        resolved = _resolve_viz_path(_VIZ_DEFAULT, now=now)
        assert resolved == tmp_path / "vrcpilot_detect_viz_20260505_123456.png"

    def test_directory_path_returns_dir_with_timestamp(self, tmp_path: Path):
        now = datetime(2026, 5, 5, 12, 34, 56)
        resolved = _resolve_viz_path(tmp_path, now=now)
        assert resolved == tmp_path / "vrcpilot_detect_viz_20260505_123456.png"

    def test_file_path_returned_as_is(self, tmp_path: Path):
        target = tmp_path / "custom.png"
        now = datetime(2026, 5, 5, 12, 34, 56)
        assert _resolve_viz_path(target, now=now) == target


class TestDetectCommandRegister:
    def test_help_runs_without_error(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``--help`` triggers SystemExit(0); the exit code is what we
        # care about, not the help text contents.
        with pytest.raises(SystemExit) as excinfo:
            main(["detect", "--help"])
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "--query" in out
        assert "--viz" in out


class TestDetectCommandYAML:
    def test_top_level_keys_no_viz(
        self,
        patched_detect: FakeDetectEngine,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        del patched_detect

        exit_code = main(["detect", "--query", str(query_png)])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert list(loaded.keys()) == [
            "captured_at",
            "window",
            "query",
            "detections",
        ]

    def test_window_values(
        self,
        patched_detect: FakeDetectEngine,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        del patched_detect

        exit_code = main(["detect", "--query", str(query_png)])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        # Defaults from _make_screenshot.
        assert loaded["window"] == {
            "x": 100,
            "y": 50,
            "width": 320,
            "height": 200,
            "monitor_index": 1,
        }

    def test_query_values(
        self,
        patched_detect: FakeDetectEngine,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        del patched_detect

        exit_code = main(["detect", "--query", str(query_png)])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert loaded["query"]["path"] == str(query_png.resolve())
        assert loaded["query"]["width"] == 48
        assert loaded["query"]["height"] == 32

    def test_detection_pos_values(
        self,
        patched_detect: FakeDetectEngine,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        del patched_detect

        exit_code = main(["detect", "--query", str(query_png)])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        det = loaded["detections"][0]
        assert det["confidence"] == pytest.approx(0.92)
        assert det["scale"] == pytest.approx(1.0)
        assert det["rotation"] == pytest.approx(0.0)
        assert det["pos"]["polygon"] == [
            [10.0, 20.0],
            [60.0, 20.0],
            [60.0, 38.0],
            [10.0, 38.0],
        ]
        assert det["pos"]["bbox"] == [10, 20, 50, 18]

    def test_captured_at_is_isoformat(
        self,
        patched_detect: FakeDetectEngine,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        del patched_detect

        exit_code = main(["detect", "--query", str(query_png)])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        parsed = datetime.fromisoformat(loaded["captured_at"])
        assert parsed == datetime(2026, 5, 5, 12, 34, 56, 789012, tzinfo=timezone.utc)


class TestDetectCommandTopK:
    def test_top_k_limits_to_highest_confidence(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
        tmp_path: Path,
    ):
        patch_stdin_with_screenshot(mocker, tmp_path)
        # Three detections in arbitrary confidence order.
        det_a = _make_detection(confidence=0.50)
        det_b = _make_detection(confidence=0.95)
        det_c = _make_detection(confidence=0.80)
        engine = FakeDetectEngine([det_a, det_b, det_c])
        _detect_module._default_engine = engine

        try:
            exit_code = main(["detect", "--query", str(query_png), "--top-k", "1"])
        finally:
            _detect_module._default_engine = None

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert len(loaded["detections"]) == 1
        assert loaded["detections"][0]["confidence"] == pytest.approx(0.95)

    def test_no_top_k_emits_all_detections(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
        tmp_path: Path,
    ):
        patch_stdin_with_screenshot(mocker, tmp_path)
        dets = [
            _make_detection(confidence=0.50),
            _make_detection(confidence=0.95),
            _make_detection(confidence=0.80),
        ]
        engine = FakeDetectEngine(dets)
        _detect_module._default_engine = engine

        try:
            exit_code = main(["detect", "--query", str(query_png)])
        finally:
            _detect_module._default_engine = None

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert len(loaded["detections"]) == 3


class TestDetectCommandViz:
    def test_no_viz_writes_no_png(
        self,
        patched_detect: FakeDetectEngine,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        query_png: Path,
    ):
        del patched_detect
        monkeypatch.chdir(tmp_path)

        exit_code = main(["detect", "--query", str(query_png)])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "viz_path" not in loaded
        # query.png is in tmp_path; viz pngs would have a
        # ``vrcpilot_detect_viz_`` prefix.
        assert list(tmp_path.glob("vrcpilot_detect_viz_*.png")) == []

    def test_viz_no_arg_writes_to_cwd(
        self,
        patched_detect: FakeDetectEngine,
        patched_render: None,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        query_png: Path,
    ):
        del patched_detect, patched_render
        monkeypatch.chdir(tmp_path)

        exit_code = main(["detect", "--query", str(query_png), "--viz"])

        assert exit_code == 0
        produced = list(tmp_path.glob("vrcpilot_detect_viz_*.png"))
        assert len(produced) == 1
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["viz_path"]) == produced[0].resolve()

    def test_viz_with_file_path(
        self,
        patched_detect: FakeDetectEngine,
        patched_render: None,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        query_png: Path,
    ):
        del patched_detect, patched_render
        target = tmp_path / "custom.png"

        exit_code = main(["detect", "--query", str(query_png), "--viz", str(target)])

        assert exit_code == 0
        assert target.is_file()
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["viz_path"]) == target.resolve()


class TestDetectCommandFailure:
    def test_query_image_unreadable(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ):
        patch_stdin_with_screenshot(mocker, tmp_path)
        missing = tmp_path / "does_not_exist.png"

        exit_code = main(["detect", "--query", str(missing)])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: could not read query image" in captured.err
        assert str(missing) in captured.err


class TestDetectCommandEngineConstruction:
    def test_threshold_passed_to_template_engine(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
        tmp_path: Path,
    ):
        patch_stdin_with_screenshot(mocker, tmp_path)
        engine_instance = FakeDetectEngine([])
        template_factory = mocker.patch(
            "vrcpilot.cli.detect.TemplateDetectEngine",
            return_value=engine_instance,
        )

        exit_code = main(
            [
                "detect",
                "--query",
                str(query_png),
                "--threshold",
                "0.9",
            ]
        )

        assert exit_code == 0
        template_factory.assert_called_once_with(threshold=0.9)
        # And the engine was actually used to produce the result.
        assert engine_instance.calls == 1
        # capsys absorbs stdout; just ensure the YAML round-trips cleanly.
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert loaded["detections"] == []

    def test_no_tuning_flags_does_not_construct_template_engine(
        self,
        mocker: MockerFixture,
        query_png: Path,
        tmp_path: Path,
    ):
        patch_stdin_with_screenshot(mocker, tmp_path)
        template_factory = mocker.patch("vrcpilot.cli.detect.TemplateDetectEngine")
        # Provide a default cached engine so detect() does not lazy-build.
        engine_instance = FakeDetectEngine([])
        _detect_module._default_engine = engine_instance

        try:
            exit_code = main(["detect", "--query", str(query_png)])
        finally:
            _detect_module._default_engine = None

        assert exit_code == 0
        template_factory.assert_not_called()
        assert engine_instance.calls == 1


class TestDetectScreenshotInputIntegration:
    """Cover the two input sources resolved by ``--screenshot`` plumbing.

    The detect engine itself is patched out via the cached
    ``_default_engine`` slot so tests stay decoupled from the real
    template matcher and only assert that the wiring funnels into
    :func:`~vrcpilot.cli._common.resolve_screenshot` correctly.
    """

    def test_flag_loads_screenshot_yaml(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        # ``write_screenshot_payload`` intentionally returns the YAML
        # text without writing the file, so flag-based tests must dump
        # it to disk themselves (stdin tests use the text directly).
        yaml_path, yaml_text = write_screenshot_payload(tmp_path)
        yaml_path.write_text(yaml_text)
        engine = FakeDetectEngine([_make_detection()])
        _detect_module._default_engine = engine

        try:
            exit_code = main(
                [
                    "detect",
                    "--query",
                    str(query_png),
                    "--screenshot",
                    str(yaml_path),
                ]
            )
        finally:
            _detect_module._default_engine = None

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "captured_at" in loaded
        assert "window" in loaded
        assert "query" in loaded
        assert "detections" in loaded

    def test_stdin_loads_screenshot_yaml(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        # ``patch_stdin_with_screenshot`` swaps sys.stdin for a
        # StringIO whose ``isatty()`` returns False — exactly the
        # piped-stdin signal resolve_screenshot looks for. The autouse
        # fixture's True override is shadowed by this fresh patch.
        patch_stdin_with_screenshot(mocker, tmp_path)
        engine = FakeDetectEngine([_make_detection()])
        _detect_module._default_engine = engine

        try:
            exit_code = main(["detect", "--query", str(query_png)])
        finally:
            _detect_module._default_engine = None

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "captured_at" in loaded
        assert "window" in loaded
        assert "query" in loaded
        assert "detections" in loaded

    def test_missing_screenshot_file_exits_1(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        detect_spy = mocker.patch("vrcpilot.cli.detect.detect")

        exit_code = main(
            [
                "detect",
                "--query",
                str(query_png),
                "--screenshot",
                "/nonexistent/path.yaml",
            ]
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: --screenshot file not found:" in captured.err
        detect_spy.assert_not_called()

    def test_malformed_screenshot_yaml_exits_1(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        # Write something that parses as YAML but is not a mapping, so
        # ``Screenshot.load`` raises ValueError and the helper turns it
        # into a single ``vrcpilot:`` stderr line.
        broken = tmp_path / "broken.yaml"
        broken.write_text("- not\n- a\n- mapping\n")
        detect_spy = mocker.patch("vrcpilot.cli.detect.detect")

        exit_code = main(
            [
                "detect",
                "--query",
                str(query_png),
                "--screenshot",
                str(broken),
            ]
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: screenshot YAML must be a mapping" in captured.err
        detect_spy.assert_not_called()


class TestDetectScreenshotInputRequirement:
    """No screenshot source = exit 1 with guidance message."""

    def test_no_source_exits_1_with_error_message(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
        query_png: Path,
    ):
        # The autouse ``_stdin_is_tty_by_default`` fixture pins
        # ``sys.stdin.isatty()`` to ``True`` so this test exercises the
        # "no flag, no pipe" branch without any extra setup.
        detect_spy = mocker.patch("vrcpilot.cli.detect.detect")

        exit_code = main(["detect", "--query", str(query_png)])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: no screenshot provided" in captured.err
        assert "--screenshot" in captured.err
        assert "stdin" in captured.err
        assert "pipe" in captured.err
        detect_spy.assert_not_called()
