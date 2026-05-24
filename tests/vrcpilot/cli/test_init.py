"""Tests for the :mod:`vrcpilot.cli` package surface.

Covers the dispatcher (:func:`vrcpilot.cli.main`), the parser built by
:func:`vrcpilot.cli.build_parser`, and the platform-conditional
``linux-mic`` registration. Per-command behaviour lives in
``test_<cmd>.py`` siblings.
"""

from __future__ import annotations

import argparse
import sys

import pytest

import vrcpilot
import vrcpilot.cli
from vrcpilot.cli import build_parser, main


class TestMainDispatch:
    """Top-level argparse dispatch."""

    def test_missing_subcommand_exits_nonzero(self):
        # ``add_subparsers(required=True)`` => argparse exits with
        # SystemExit when no subcommand is supplied.
        with pytest.raises(SystemExit) as excinfo:
            main([])
        assert excinfo.value.code != 0

    def test_version_flag_prints_package_version(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``--version`` is an argparse ``version`` action that calls
        # SystemExit(0) after printing.
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])

        assert excinfo.value.code == 0
        assert vrcpilot.__version__ in capsys.readouterr().out


class TestBuildParser:
    """``build_parser()`` should expose every documented subcommand."""

    def test_returns_argument_parser(self):
        assert isinstance(build_parser(), argparse.ArgumentParser)

    @pytest.mark.parametrize(
        "subcommand",
        [
            "launch",
            "pid",
            "terminate",
            "focus",
            "unfocus",
            "screenshot",
            "record",
            "mic",
            "mouse",
            "keyboard",
            "paste",
            "ocr",
            "detect",
            "osc",
        ],
    )
    def test_subcommand_is_registered(self, subcommand: str):
        parser = build_parser()
        subparsers_action = parser._subparsers._group_actions[0]  # type: ignore[union-attr]
        assert subcommand in subparsers_action.choices


class TestLinuxMicRegistration:
    """``linux-mic`` is wired in only when running on Linux."""

    def test_linux_mic_present_on_linux(self):
        if sys.platform != "linux":
            pytest.skip("linux-mic is registered only on Linux")
        parser = build_parser()
        subparsers_action = parser._subparsers._group_actions[0]  # type: ignore[union-attr]
        assert "linux-mic" in subparsers_action.choices

    def test_linux_mic_absent_on_windows(self):
        if sys.platform == "linux":
            pytest.skip("linux-mic is intentionally registered on Linux")
        parser = build_parser()
        subparsers_action = parser._subparsers._group_actions[0]  # type: ignore[union-attr]
        assert "linux-mic" not in subparsers_action.choices


class TestArgcompleteCompleters:
    """File-path completers wired via :func:`_common.attach_completer`.

    The Linux + Windows shells both lean on these completers for tab
    expansion; assert each registered completer at least surfaces its
    file-suffix filter so regressions in the wiring are caught here
    rather than at the shell layer.
    """

    def _subparser(self, name: str) -> argparse.ArgumentParser:
        parser = build_parser()
        subparsers_action = parser._subparsers._group_actions[0]  # type: ignore[union-attr]
        return subparsers_action.choices[name]

    def _action(self, parser: argparse.ArgumentParser, option: str) -> argparse.Action:
        return next(
            action for action in parser._actions if option in action.option_strings
        )

    def test_screenshot_output_completer_filters_png(self):
        action = self._action(self._subparser("screenshot"), "--output")
        completer = action.completer  # type: ignore[attr-defined]
        # FilesCompleter.allowednames is normalized; "png" should appear.
        assert any("png" in name for name in completer.allowednames)

    def test_record_output_completer_filters_mp4_and_wav(self):
        action = self._action(self._subparser("record"), "--output")
        completer = action.completer  # type: ignore[attr-defined]
        assert any("mp4" in name for name in completer.allowednames)
        assert any("wav" in name for name in completer.allowednames)


class TestArgcompleteRuntime:
    """``main`` must not block on argcomplete in a normal (non-completion) run.

    Real ``argcomplete.autocomplete`` is a no-op when ``_ARGCOMPLETE`` is
    unset; deleting that env var is the documented way to take the
    no-op branch. ``pid`` against the autouse empty ``process_iter`` is
    the cheapest fully-real path through ``main``.
    """

    def test_pid_returns_when_argcomplete_env_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.delenv("_ARGCOMPLETE", raising=False)

        # ``pid`` with no running VRChat (autouse default) -> exit 1.
        # The point is reaching the return at all; if argcomplete tried
        # to take over, this call would never return.
        assert main(["pid"]) == 1
