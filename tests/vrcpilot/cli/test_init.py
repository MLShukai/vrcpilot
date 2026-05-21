"""Tests for the :mod:`vrcpilot.cli` package surface.

Covers the dispatcher (:func:`vrcpilot.cli.main`) and the
``argcomplete`` integration on the parser built by
:func:`vrcpilot.cli.build_parser`. Per-command behaviour lives in
``test_<cmd>.py`` siblings.
"""

from __future__ import annotations

import argparse

import pytest
from argcomplete.completers import FilesCompleter
from pytest_mock import MockerFixture

from vrcpilot.cli import build_parser, main


class TestMain:
    def test_missing_subcommand_exits(self):
        with pytest.raises(SystemExit):
            main([])

    def test_version_prints_package_version(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        import vrcpilot

        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])

        assert excinfo.value.code == 0
        captured = capsys.readouterr()
        assert vrcpilot.__version__ in captured.out


class TestArgcompleteIntegration:
    def test_autocomplete_invoked_with_parser(self, mocker: MockerFixture):
        # ``pid`` against the autouse empty ``process_iter`` is the
        # cheapest fully-real path through ``main``.
        autocomplete_mock = mocker.patch("vrcpilot.cli.argcomplete.autocomplete")

        exit_code = main(["pid"])

        assert exit_code == 1
        autocomplete_mock.assert_called_once()
        call_args = autocomplete_mock.call_args
        assert isinstance(call_args.args[0], argparse.ArgumentParser)

    def test_steam_path_has_files_completer(self):
        parser = build_parser()

        subparsers_action = parser._subparsers._group_actions[0]  # type: ignore[union-attr]
        launch_parser = subparsers_action.choices["launch"]
        steam_path_action = next(
            action
            for action in launch_parser._actions
            if "--steam-path" in action.option_strings
        )

        completer = steam_path_action.completer  # type: ignore[attr-defined]
        assert isinstance(completer, FilesCompleter)
        # argcomplete normalizes allowednames; "exe" should appear in some form.
        allowednames = completer.allowednames
        assert any("exe" in name for name in allowednames)

    def test_autocomplete_does_not_block_normal_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.delenv("_ARGCOMPLETE", raising=False)

        exit_code = main(["pid"])

        assert exit_code == 1

    def test_capture_output_has_files_completer(self):
        parser = build_parser()

        subparsers_action = parser._subparsers._group_actions[0]  # type: ignore[union-attr]
        capture_parser = subparsers_action.choices["capture"]
        output_action = next(
            action
            for action in capture_parser._actions
            if "--output" in action.option_strings
        )

        completer = output_action.completer  # type: ignore[attr-defined]
        assert isinstance(completer, FilesCompleter)
        allowednames = completer.allowednames
        assert any("mp4" in name for name in allowednames)

    def test_record_output_has_files_completer(self):
        parser = build_parser()

        subparsers_action = parser._subparsers._group_actions[0]  # type: ignore[union-attr]
        record_parser = subparsers_action.choices["record"]
        output_action = next(
            action
            for action in record_parser._actions
            if "--output" in action.option_strings
        )

        completer = output_action.completer  # type: ignore[attr-defined]
        assert isinstance(completer, FilesCompleter)
        allowednames = completer.allowednames
        assert any("wav" in name for name in allowednames)
