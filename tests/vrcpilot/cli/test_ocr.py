"""Tests for :mod:`vrcpilot.cli.ocr`."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml
from pytest_mock import MockerFixture

from tests.fakes import patch_stdin_with_screenshot, write_screenshot_payload
from vrcpilot.cli import main
from vrcpilot.cli.ocr import _VIZ_DEFAULT, _resolve_viz_path
from vrcpilot.ocr import OCRResult, OCRWord
from vrcpilot.screenshot import Screenshot


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
        captured_at = datetime(2026, 5, 3, 12, 34, 56, 789012, tzinfo=timezone.utc)
    return Screenshot(
        image=np.zeros((height, width, 3), dtype=np.uint8),
        x=x,
        y=y,
        width=width,
        height=height,
        monitor_index=monitor_index,
        captured_at=captured_at,
    )


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


def _make_result(*, words: tuple[OCRWord, ...] | None = None) -> OCRResult:
    if words is None:
        words = (_make_word(),)
    return OCRResult(screenshot=_make_screenshot(), words=words)


@pytest.fixture
def patched_ocr(mocker: MockerFixture, tmp_path: Path) -> OCRResult:
    """Patch the OCR boundary and feed a screenshot via piped stdin.

    Since commit 10 removed the live-capture fallback,
    :func:`vrcpilot.cli._common.resolve_screenshot` only honours
    ``--screenshot`` or piped stdin. This fixture takes the stdin path
    via :func:`patch_stdin_with_screenshot` so ``ocr`` reads the YAML on
    demand. ``ocr`` is patched in the ocr module where it is
    imported so the test never touches the real engine.
    """
    shot = _make_screenshot()
    result = OCRResult(screenshot=shot, words=(_make_word(),))
    patch_stdin_with_screenshot(mocker, tmp_path)
    mocker.patch("vrcpilot.cli.ocr.ocr", return_value=result)
    return result


@pytest.fixture
def patched_render(mocker: MockerFixture) -> None:
    """Patch the visualization boundary so unit tests skip the real cv2
    draw."""
    rendered = np.zeros((200, 320, 3), dtype=np.uint8)
    mocker.patch("vrcpilot.cli.ocr.render", return_value=rendered)


class TestResolveVizPath:
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


class TestOCRCommandYAML:
    def test_top_level_keys_no_viz(
        self,
        patched_ocr: OCRResult,
        capsys: pytest.CaptureFixture[str],
    ):
        del patched_ocr

        exit_code = main(["ocr"])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert list(loaded.keys()) == ["captured_at", "window", "words"]

    def test_window_key_order(
        self,
        patched_ocr: OCRResult,
        capsys: pytest.CaptureFixture[str],
    ):
        del patched_ocr

        exit_code = main(["ocr"])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert list(loaded["window"].keys()) == [
            "x",
            "y",
            "width",
            "height",
            "monitor_index",
        ]

    def test_word_key_order(
        self,
        patched_ocr: OCRResult,
        capsys: pytest.CaptureFixture[str],
    ):
        del patched_ocr

        exit_code = main(["ocr"])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        word = loaded["words"][0]
        assert list(word.keys()) == ["text", "confidence", "pos"]
        assert list(word["pos"].keys()) == ["polygon", "bbox"]

    def test_pos_values(
        self,
        patched_ocr: OCRResult,
        capsys: pytest.CaptureFixture[str],
    ):
        del patched_ocr

        exit_code = main(["ocr"])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        word = loaded["words"][0]
        assert word["text"] == "Hello"
        assert word["confidence"] == pytest.approx(0.97)
        assert word["pos"]["polygon"] == [[10, 20], [60, 20], [60, 38], [10, 38]]
        assert word["pos"]["bbox"] == [10, 20, 50, 18]

    def test_window_values(
        self,
        patched_ocr: OCRResult,
        capsys: pytest.CaptureFixture[str],
    ):
        result = patched_ocr

        exit_code = main(["ocr"])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        shot = result.screenshot
        assert loaded["window"]["x"] == shot.x
        assert loaded["window"]["y"] == shot.y
        assert loaded["window"]["width"] == shot.width
        assert loaded["window"]["height"] == shot.height
        assert loaded["window"]["monitor_index"] == shot.monitor_index

    def test_captured_at_is_isoformat(
        self,
        patched_ocr: OCRResult,
        capsys: pytest.CaptureFixture[str],
    ):
        result = patched_ocr

        exit_code = main(["ocr"])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        parsed = datetime.fromisoformat(loaded["captured_at"])
        assert parsed == result.screenshot.captured_at


class TestOCRCommandViz:
    def test_no_viz_writes_no_png(
        self,
        patched_ocr: OCRResult,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        del patched_ocr
        monkeypatch.chdir(tmp_path)

        exit_code = main(["ocr"])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "viz_path" not in loaded
        # The fixture writes ``screenshot.png`` in tmp_path to feed a
        # screenshot YAML on stdin; viz pngs would have a
        # ``vrcpilot_ocr_viz_`` prefix.
        assert list(tmp_path.glob("vrcpilot_ocr_viz_*.png")) == []

    def test_viz_no_arg_writes_to_cwd(
        self,
        patched_ocr: OCRResult,
        patched_render: None,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        del patched_ocr, patched_render
        monkeypatch.chdir(tmp_path)

        exit_code = main(["ocr", "--viz"])

        assert exit_code == 0
        produced = list(tmp_path.glob("vrcpilot_ocr_viz_*.png"))
        assert len(produced) == 1
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["viz_path"]) == produced[0].resolve()

    def test_viz_with_file_path(
        self,
        patched_ocr: OCRResult,
        patched_render: None,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ):
        del patched_ocr, patched_render
        target = tmp_path / "custom.png"

        exit_code = main(["ocr", "--viz", str(target)])

        assert exit_code == 0
        assert target.is_file()
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["viz_path"]) == target.resolve()

    def test_viz_with_directory(
        self,
        patched_ocr: OCRResult,
        patched_render: None,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ):
        del patched_ocr, patched_render

        exit_code = main(["ocr", "--viz", str(tmp_path)])

        assert exit_code == 0
        produced = list(tmp_path.glob("vrcpilot_ocr_viz_*.png"))
        assert len(produced) == 1
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert Path(loaded["viz_path"]) == produced[0].resolve()


class TestOCRScreenshotInputIntegration:
    """Cover the two input sources resolved by ``--screenshot`` plumbing.

    OCR itself is patched out so tests stay decoupled from the real
    OCR engine and only assert that the wiring funnels into
    :func:`~vrcpilot.cli._common.resolve_screenshot` correctly.
    """

    def test_flag_loads_screenshot_yaml(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``write_screenshot_payload`` intentionally returns the YAML
        # text without writing the file, so flag-based tests must dump
        # it to disk themselves (stdin tests use the text directly).
        yaml_path, yaml_text = write_screenshot_payload(tmp_path)
        yaml_path.write_text(yaml_text)
        # Stub out OCR so the test never touches the real engine.
        result = _make_result()
        mocker.patch("vrcpilot.cli.ocr.ocr", return_value=result)

        exit_code = main(["ocr", "--screenshot", str(yaml_path)])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "captured_at" in loaded
        assert "window" in loaded
        assert "words" in loaded

    def test_stdin_loads_screenshot_yaml(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``patch_stdin_with_screenshot`` swaps sys.stdin for a
        # StringIO whose ``isatty()`` returns False — exactly the
        # piped-stdin signal resolve_screenshot looks for. The autouse
        # fixture's True override is shadowed by this fresh patch.
        patch_stdin_with_screenshot(mocker, tmp_path)
        result = _make_result()
        mocker.patch("vrcpilot.cli.ocr.ocr", return_value=result)

        exit_code = main(["ocr"])

        assert exit_code == 0
        loaded = yaml.safe_load(capsys.readouterr().out)
        assert "captured_at" in loaded
        assert "window" in loaded
        assert "words" in loaded

    def test_missing_screenshot_file_exits_1(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        ocr_spy = mocker.patch("vrcpilot.cli.ocr.ocr")

        exit_code = main(["ocr", "--screenshot", "/nonexistent/path.yaml"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: --screenshot file not found:" in captured.err
        ocr_spy.assert_not_called()

    def test_malformed_screenshot_yaml_exits_1(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        # Write something that parses as YAML but is not a mapping, so
        # ``Screenshot.load`` raises ValueError and the helper turns it
        # into a single ``vrcpilot:`` stderr line.
        broken = tmp_path / "broken.yaml"
        broken.write_text("- not\n- a\n- mapping\n")
        ocr_spy = mocker.patch("vrcpilot.cli.ocr.ocr")

        exit_code = main(["ocr", "--screenshot", str(broken)])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: screenshot YAML must be a mapping" in captured.err
        ocr_spy.assert_not_called()


class TestOCRScreenshotInputRequirement:
    """No screenshot source = exit 1 with guidance message."""

    def test_no_source_exits_1_with_error_message(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        # The autouse ``_stdin_is_tty_by_default`` fixture pins
        # ``sys.stdin.isatty()`` to ``True`` so this test exercises the
        # "no flag, no pipe" branch without any extra setup.
        ocr_spy = mocker.patch("vrcpilot.cli.ocr.ocr")

        exit_code = main(["ocr"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: no screenshot provided" in captured.err
        assert "--screenshot" in captured.err
        assert "stdin" in captured.err
        assert "pipe" in captured.err
        ocr_spy.assert_not_called()
