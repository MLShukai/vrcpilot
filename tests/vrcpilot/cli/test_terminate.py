"""Tests for :mod:`vrcpilot.cli.terminate`.

``vrcpilot terminate`` is the CLI front-end of
:func:`vrcpilot.process.terminate`. Two behaviours are spec'd:

* Without positional PIDs, kill every running VRChat (silent + exit 0
  when there is nothing to kill, prints the killed PIDs otherwise).
* With explicit PIDs, validate each one against the actual process
  name. An explicit non-VRChat PID raises ``ValueError`` which the CLI
  maps to exit 1 plus a ``vrcpilot: ...`` stderr line.

Tests below exercise the negative paths against the autouse empty
``psutil.process_iter`` and against a real PID known not to be VRChat
(the test runner's own PID). Killing live VRChat processes is e2e
territory and deferred.
"""

from __future__ import annotations

import os

import pytest

from vrcpilot.cli import main


class TestTerminateNoArgs:
    """``terminate`` with no positional PIDs and no running VRChat."""

    def test_silent_exit_0_when_nothing_to_kill(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # Autouse ``_no_real_vrchat`` empties ``process_iter`` -- the
        # ``terminate`` API observes zero targets and returns ``[]``.
        # The CLI prints nothing and exits 0 (idempotent contract).
        assert main(["terminate"]) == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestTerminatePositionalPids:
    """Explicit positional PIDs select which processes to kill."""

    def test_argparse_rejects_non_int_positional(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``type=int`` on the positional makes argparse refuse non-ints
        # with its usual exit-2 error before ``terminate`` runs.
        with pytest.raises(SystemExit) as excinfo:
            main(["terminate", "not-an-int"])

        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_unknown_pid_is_silently_skipped(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # An unreachable PID raises ``psutil.NoSuchProcess`` inside
        # ``terminate``; the production code treats that as success so
        # callers can re-run the command idempotently.
        # ``2**31 - 1`` is the maximum 32-bit signed PID; vanishingly
        # unlikely to be allocated on a real host.
        unreachable_pid = 2**31 - 1
        assert main(["terminate", str(unreachable_pid)]) == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_non_vrchat_pid_exits_1_with_diagnostic(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # The test runner's own PID definitely exists and definitely is
        # not ``VRChat.exe`` -- ``terminate`` raises ``ValueError`` and
        # the CLI maps that to exit 1 + a ``vrcpilot: ...`` stderr line.
        test_pid = os.getpid()
        assert main(["terminate", str(test_pid)]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert f"PID {test_pid} is not a VRChat process" in captured.err
        assert "vrcpilot:" in captured.err
