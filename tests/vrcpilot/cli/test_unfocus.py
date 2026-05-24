"""Tests for :mod:`vrcpilot.cli.unfocus`.

``vrcpilot unfocus`` mirrors :mod:`vrcpilot.cli.focus`: a thin shell
over :func:`vrcpilot.window.unfocus`. The contract has the same shape:

* No VRChat running -> exit 1 with ``vrcpilot: could not unfocus
  VRChat`` on stderr.
* Argparse plumbing: ``--pid`` is an int that gets forwarded.

Live success-path verification (real X11 / Win32 z-order shuffling)
requires a real VRChat instance and is deferred to the e2e suite.
"""

from __future__ import annotations

import pytest

from vrcpilot.cli import build_parser, main


class TestUnfocusNoVRChat:
    """Without a VRChat process running, ``unfocus`` exits 1."""

    def test_exits_with_code_one(self):
        assert main(["unfocus"]) == 1

    def test_stderr_has_diagnostic_message(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        main(["unfocus"])
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: could not unfocus VRChat" in captured.err

    def test_explicit_pid_also_exits_1_when_window_missing(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``resolve_pid`` accepts the explicit pid without checking
        # liveness; the backend then fails to find a matching window
        # and the CLI surfaces the failure as exit 1.
        assert main(["unfocus", "--pid", "12345"]) == 1
        assert "vrcpilot: could not unfocus VRChat" in capsys.readouterr().err


class TestUnfocusArgparse:
    """``--pid`` parsing on the unfocus subparser."""

    def test_pid_flag_accepts_int(self):
        ns = build_parser().parse_args(["unfocus", "--pid", "9876"])
        assert ns.pid == 9876

    def test_no_pid_defaults_to_none(self):
        ns = build_parser().parse_args(["unfocus"])
        assert ns.pid is None
