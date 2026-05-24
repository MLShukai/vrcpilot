"""Tests for :mod:`vrcpilot.cli.mouse`.

The mouse CLI's job is argv parsing plus dispatch to
:func:`vrcpilot.controls.mouse.{move,click,scroll}`. Each backend
call goes through ``ensure_target`` (focus guard); without a running
VRChat the guard raises :class:`VRChatNotRunningError`, the CLI
catches it, prints ``vrcpilot: ...`` to stderr, and exits 1.

The Linux backend's constructor (``LinuxMouse.__init__``) eagerly
calls ``mss.MSS()`` to size the desktop, so even the failure path
needs a real X11 display to reach ``ensure_target``. The "no VRChat"
tests below therefore skip when no X server is reachable; the
Windows backend (``Win32Mouse``) has no equivalent eager dependency.
Real synthetic input verification is deferred to the e2e suite on
both platforms.
"""

from __future__ import annotations

import sys

import pytest

from tests.helpers import has_x11_display
from vrcpilot.cli import build_parser, main

#: Skip the focus-guard tests when the platform backend's eager
#: dependencies cannot be initialised. On Linux without an X display
#: ``LinuxMouse.__init__`` raises ``XError`` from ``mss.MSS()`` before
#: ``ensure_target`` ever runs; on Windows ``Win32Mouse`` has no
#: equivalent eager dependency so the marker is a no-op there.
_requires_real_backend = pytest.mark.skipif(
    sys.platform == "linux" and not has_x11_display(),
    reason="LinuxMouse needs an X11 display to construct",
)


class TestMouseArgparse:
    """Subcommand-level argparse plumbing."""

    def test_move_parses_x_y_as_int(self):
        ns = build_parser().parse_args(["mouse", "move", "100", "200"])
        assert ns.mouse_action == "move"
        assert ns.x == 100
        assert ns.y == 200
        assert ns.rel is False

    def test_move_rel_flag(self):
        ns = build_parser().parse_args(["mouse", "move", "10", "-20", "--rel"])
        assert ns.rel is True

    def test_click_default_no_buttons(self):
        ns = build_parser().parse_args(["mouse", "click"])
        assert ns.mouse_action == "click"
        assert ns.button == []
        assert ns.count == 1
        assert ns.duration == pytest.approx(0.0)

    def test_click_count_and_duration(self):
        ns = build_parser().parse_args(
            ["mouse", "click", "--count", "3", "--duration", "0.25"]
        )
        assert ns.count == 3
        assert ns.duration == pytest.approx(0.25)

    def test_scroll_parses_amount_as_int(self):
        ns = build_parser().parse_args(["mouse", "scroll", "-5"])
        assert ns.mouse_action == "scroll"
        assert ns.amount == -5

    def test_action_required(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["mouse"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_move_requires_x_y_positional(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["mouse", "move"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""


@_requires_real_backend
class TestMouseNoVRChat:
    """The focus guard fires when no VRChat is running."""

    def test_move_exits_1(
        self,
        not_wayland_native: None,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``mouse.move`` invokes ``ensure_target`` which calls
        # ``resolve_pid``. The autouse empty ``process_iter`` makes
        # ``resolve_pid`` raise ``VRChatNotRunningError``; the CLI
        # catches it and exits 1 with a ``vrcpilot: ...`` line.
        assert main(["mouse", "move", "1", "2"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err

    def test_click_exits_1(
        self,
        not_wayland_native: None,
        capsys: pytest.CaptureFixture[str],
    ):
        assert main(["mouse", "click"]) == 1
        assert "vrcpilot:" in capsys.readouterr().err

    def test_scroll_exits_1(
        self,
        not_wayland_native: None,
        capsys: pytest.CaptureFixture[str],
    ):
        assert main(["mouse", "scroll", "1"]) == 1
        assert "vrcpilot:" in capsys.readouterr().err
