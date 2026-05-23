"""Tests for :mod:`vrcpilot.cli.paste`.

The CLI delegates to :func:`vrcpilot.clipboard.paste` -- patching
``vrcpilot.cli.paste.clipboard.paste`` lets each test stub out the real
keyboard / pyperclip pipeline and assert the CLI behaviour in isolation.
The stdin fallback and tty guard are exercised by patching
``vrcpilot.cli.paste.sys.stdin``.
"""

from __future__ import annotations

import io

import pyperclip
import pytest
from pytest_mock import MockerFixture

from vrcpilot.cli import main
from vrcpilot.controls import VRChatNotFocusedError
from vrcpilot.process import VRChatNotRunningError


@pytest.fixture
def fake_paste(mocker: MockerFixture):
    """Stub out :func:`vrcpilot.clipboard.paste` reached via the CLI module."""
    return mocker.patch("vrcpilot.cli.paste.clipboard.paste")


@pytest.fixture
def tty_stdin(mocker: MockerFixture) -> None:
    """Force ``sys.stdin.isatty()`` to ``True`` for the CLI module."""
    mocker.patch("vrcpilot.cli.paste.sys.stdin.isatty", return_value=True)


class TestPasteSuccessPath:
    def test_positional_text_is_forwarded(
        self,
        fake_paste,
        capsys: pytest.CaptureFixture[str],
    ):
        exit_code = main(["paste", "hello"])

        assert exit_code == 0
        fake_paste.assert_called_once_with("hello")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_japanese_text_round_trips(self, fake_paste):
        exit_code = main(["paste", "こんにちは"])

        assert exit_code == 0
        fake_paste.assert_called_once_with("こんにちは")

    def test_silent_on_success(self, fake_paste, capsys: pytest.CaptureFixture[str]):
        del fake_paste
        exit_code = main(["paste", "hi"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestPasteStdinFallback:
    def test_stdin_is_read_when_positional_omitted(
        self, fake_paste, mocker: MockerFixture
    ):
        # Piped stdin: not a tty, so the CLI consumes its full contents.
        mocker.patch(
            "vrcpilot.cli.paste.sys.stdin",
            new=io.StringIO("piped\ntext\n"),
        )
        # ``StringIO.isatty`` already returns False, so no extra patch needed.

        exit_code = main(["paste"])

        assert exit_code == 0
        fake_paste.assert_called_once_with("piped\ntext\n")

    def test_tty_with_no_text_exits_2(
        self,
        tty_stdin: None,
        fake_paste,
        capsys: pytest.CaptureFixture[str],
    ):
        del tty_stdin
        exit_code = main(["paste"])

        assert exit_code == 2
        fake_paste.assert_not_called()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: no text provided" in captured.err


class TestPasteGuardErrors:
    def test_not_running_error_returns_exit_1(
        self,
        fake_paste,
        capsys: pytest.CaptureFixture[str],
    ):
        fake_paste.side_effect = VRChatNotRunningError("VRChat is not running")

        exit_code = main(["paste", "hi"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("vrcpilot:")
        assert "VRChat is not running" in captured.err

    def test_not_focused_error_returns_exit_1(
        self,
        fake_paste,
        capsys: pytest.CaptureFixture[str],
    ):
        fake_paste.side_effect = VRChatNotFocusedError("VRChat is not focused")

        exit_code = main(["paste", "hi"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("vrcpilot:")
        assert "VRChat is not focused" in captured.err


class TestPastePyperclipError:
    def test_pyperclip_exception_returns_exit_1(
        self,
        fake_paste,
        capsys: pytest.CaptureFixture[str],
    ):
        fake_paste.side_effect = pyperclip.PyperclipException("xclip not found")

        exit_code = main(["paste", "hi"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: xclip not found" in captured.err
