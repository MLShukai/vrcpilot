"""Tests for :mod:`vrcpilot.cli.paste`.

``vrcpilot paste`` copies a string to the clipboard and sends Ctrl+V
into VRChat. The text comes from the positional arg or piped stdin;
running it on a TTY with no positional argument exits 2 (would block
forever otherwise).

Contract points testable without a live VRChat:

* Argparse plumbing (positional ``text`` is optional).
* TTY + no positional argument -> exit 2 with a stderr line.
* No VRChat running -> exit 1 from the focus-guard branch.

The clipboard write itself goes through ``pyperclip`` which requires
a display server; success-path verification is deferred to the e2e
suite.
"""

from __future__ import annotations

import io

import pytest
from pytest_mock import MockerFixture

from vrcpilot.cli import build_parser, main


class TestPasteArgparse:
    def test_text_positional_is_optional(self):
        ns = build_parser().parse_args(["paste"])
        assert ns.text is None

    def test_text_positional_captured(self):
        ns = build_parser().parse_args(["paste", "hello"])
        assert ns.text == "hello"

    def test_pid_flag(self):
        ns = build_parser().parse_args(["paste", "x", "--pid", "111"])
        assert ns.pid == 111


class TestPasteNoTextOnTty:
    """No positional + TTY stdin -> exit 2 with a guidance line."""

    def test_exits_2(self, capsys: pytest.CaptureFixture[str]):
        # The autouse stdin-isatty fixture pins ``True``; the per-
        # subcommand call checks ``sys.stdin.isatty`` directly.
        # ``paste`` reads its own ``sys.stdin``, which inherits from
        # the runner; we pin it to a tty separately.
        # (CLI reads ``sys.stdin.isatty`` from ``vrcpilot.cli.paste``.)
        assert main(["paste"]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: no text provided" in captured.err


class TestPasteNoVRChat:
    """The focus guard fires when no VRChat is running."""

    def test_positional_text_exits_1(
        self,
        not_wayland_native: None,
        capsys: pytest.CaptureFixture[str],
    ):
        # Real text input + autouse no-VRChat means ``clipboard.paste``
        # reaches ``ensure_target`` and that raises
        # ``VRChatNotRunningError`` -- exit 1 with diagnostic.
        del not_wayland_native
        assert main(["paste", "hello"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_stdin_text_exits_1(
        self,
        not_wayland_native: None,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del not_wayland_native
        # Pipe a string in via stdin -- ``paste`` reads it because
        # ``isatty()`` on a ``StringIO`` returns False natively.
        mocker.patch("vrcpilot.cli.paste.sys.stdin", new=io.StringIO("piped"))
        assert main(["paste"]) == 1
        assert "vrcpilot:" in capsys.readouterr().err
