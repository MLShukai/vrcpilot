"""Unit tests for :mod:`vrcpilot.cli._common`.

The helpers under test are pure functions over a real
``argparse.Namespace`` plus an on-disk YAML file -- no mocking
required for the file branch. The stdin branch is covered through the
documented stdin patch in :mod:`tests.fakes.screenshot`.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.fakes import write_screenshot_payload
from vrcpilot.cli._common import (
    add_pid_arg,
    add_screenshot_input_arg,
    handle_multi_instance_error,
    resolve_screenshot,
)
from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.screenshot import Screenshot


class TestAddPidArg:
    """``add_pid_arg`` wires a ``--pid`` int flag onto a parser."""

    def test_default_is_none(self):
        parser = argparse.ArgumentParser()
        add_pid_arg(parser)
        ns = parser.parse_args([])
        assert ns.pid is None

    def test_int_value_captured(self):
        parser = argparse.ArgumentParser()
        add_pid_arg(parser)
        ns = parser.parse_args(["--pid", "4242"])
        assert ns.pid == 4242

    def test_non_int_rejected_by_argparse(self, capsys: pytest.CaptureFixture[str]):
        parser = argparse.ArgumentParser()
        add_pid_arg(parser)
        with pytest.raises(SystemExit):
            parser.parse_args(["--pid", "not-an-int"])
        assert capsys.readouterr().err != ""


class TestHandleMultiInstanceError:
    """Stderr diagnostic shape for the multi-instance branch."""

    def test_lists_pids_with_separator(self, capsys: pytest.CaptureFixture[str]):
        handle_multi_instance_error(VRChatMultipleInstancesError([111, 222, 333]))
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "PIDs: 111 222 333" in captured.err
        assert "pass --pid" in captured.err

    def test_single_pid_path(self, capsys: pytest.CaptureFixture[str]):
        # Even with a single PID the diagnostic still uses the same
        # ``PIDs:`` prefix so callers can grep without special-casing.
        handle_multi_instance_error(VRChatMultipleInstancesError([42]))
        captured = capsys.readouterr()
        assert "PIDs: 42" in captured.err


class TestAddScreenshotInputArg:
    def test_short_and_long_form_resolve_to_same_arg(self, tmp_path: Path):
        parser = argparse.ArgumentParser()
        add_screenshot_input_arg(parser)

        target = tmp_path / "shot.yaml"
        short = parser.parse_args(["-s", str(target)])
        long_form = parser.parse_args(["--screenshot", str(target)])
        assert short.screenshot == target
        assert long_form.screenshot == target

    def test_default_is_none(self):
        parser = argparse.ArgumentParser()
        add_screenshot_input_arg(parser)
        ns = parser.parse_args([])
        assert ns.screenshot is None


class TestResolveScreenshot:
    """Cover all four branches of :func:`resolve_screenshot`.

    The autouse ``_stdin_is_tty_by_default`` fixture pins
    ``sys.stdin.isatty()`` to ``True``, so the "no source" and
    "explicit file" branches run without any extra setup. The piped-
    stdin branch overrides stdin via :class:`io.StringIO`.
    """

    def _namespace(self, screenshot: Path | None) -> argparse.Namespace:
        ns = argparse.Namespace()
        ns.screenshot = screenshot
        return ns

    def test_explicit_file_returns_screenshot(self, tmp_path: Path):
        yaml_path, yaml_text = write_screenshot_payload(tmp_path)
        yaml_path.write_text(yaml_text)

        result = resolve_screenshot(self._namespace(yaml_path))

        assert isinstance(result, Screenshot)
        # Round-trip preserves the geometry the fixture seeded.
        assert result.x == 100
        assert result.y == 50
        assert result.width == 64
        assert result.height == 48

    def test_missing_file_returns_none_and_writes_stderr(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        missing = tmp_path / "does-not-exist.yaml"
        assert resolve_screenshot(self._namespace(missing)) is None
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: --screenshot file not found:" in captured.err

    def test_malformed_yaml_returns_none_and_writes_stderr(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        bad = tmp_path / "bad.yaml"
        bad.write_text("- not\n- a\n- mapping\n")
        assert resolve_screenshot(self._namespace(bad)) is None
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_no_source_returns_none_with_guidance(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        assert resolve_screenshot(self._namespace(None)) is None
        captured = capsys.readouterr()
        assert captured.out == ""
        # The guidance line mentions both inputs the CLI accepts so
        # users see how to recover regardless of how they invoked it.
        assert "vrcpilot: no screenshot provided" in captured.err
        assert "--screenshot" in captured.err
        assert "stdin" in captured.err

    def test_stdin_pipe_returns_screenshot(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ):
        _, yaml_text = write_screenshot_payload(tmp_path)
        # StringIO.isatty() returns False natively -- exactly the piped
        # stdin signal ``resolve_screenshot`` checks for.
        mocker.patch("vrcpilot.cli._common.sys.stdin", new=io.StringIO(yaml_text))
        result = resolve_screenshot(self._namespace(None))
        assert isinstance(result, Screenshot)
        assert result.x == 100

    def test_flag_wins_over_stdin_when_both_present(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
    ):
        # When both --screenshot and a piped stdin are present, the
        # documented precedence picks the file flag and silently
        # discards the stdin payload.
        yaml_path, file_text = write_screenshot_payload(tmp_path, x=10, y=20)
        yaml_path.write_text(file_text)
        _, stdin_text = write_screenshot_payload(tmp_path, x=999, y=999)
        mocker.patch("vrcpilot.cli._common.sys.stdin", new=io.StringIO(stdin_text))
        result = resolve_screenshot(self._namespace(yaml_path))
        assert isinstance(result, Screenshot)
        # The file's x=10 (not stdin's 999) wins.
        assert result.x == 10
        assert result.y == 20
