"""Tests for :mod:`vrcpilot.cli.focus`.

``vrcpilot focus`` is a thin shell over :func:`vrcpilot.window.focus`.
Two contract points belong here:

* When VRChat is not running (autouse default), the window function
  cannot resolve a PID, returns ``False``, and the CLI exits 1 with a
  single ``vrcpilot: could not focus VRChat`` stderr line.
* Argparse plumbing: ``--pid`` is accepted as an int and forwarded to
  the window API.

Bringing a real VRChat window to the foreground requires the OS-level
window backend + a live VRChat -- both deferred to the e2e suite.
"""

from __future__ import annotations

import pytest

from vrcpilot.cli import build_parser, main


class TestFocusNoVRChat:
    """Without a VRChat process running, ``focus`` exits 1."""

    def test_exits_with_code_one(self):
        # ``vrcpilot.window.focus`` calls ``resolve_pid`` which observes
        # the autouse empty ``process_iter`` and converts the missing
        # process to ``False`` -- the CLI maps that to exit 1.
        assert main(["focus"]) == 1

    def test_stderr_has_diagnostic_message(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        main(["focus"])
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: could not focus VRChat" in captured.err

    def test_explicit_pid_also_exits_1_when_pid_is_dead(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``--pid`` short-circuits the lookup but the PID still has to
        # resolve to a VRChat window. The autouse empty ``process_iter``
        # means ``resolve_pid`` accepts the explicit pid (no enumeration)
        # but the platform backend cannot find the window and returns
        # False, which surfaces as exit 1.
        assert main(["focus", "--pid", "12345"]) == 1
        assert "vrcpilot: could not focus VRChat" in capsys.readouterr().err


class TestFocusArgparse:
    """``--pid`` parsing on the focus subparser."""

    def test_pid_flag_accepts_int(self):
        parser = build_parser()
        # parse_args returns a Namespace; assert the int was captured.
        ns = parser.parse_args(["focus", "--pid", "9876"])
        assert ns.pid == 9876

    def test_no_pid_defaults_to_none(self):
        parser = build_parser()
        ns = parser.parse_args(["focus"])
        assert ns.pid is None

    def test_non_int_pid_rejected_by_argparse(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        with pytest.raises(SystemExit) as excinfo:
            main(["focus", "--pid", "not-an-int"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""
