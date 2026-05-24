"""Tests for :mod:`vrcpilot.cli.pid`.

``vrcpilot pid`` is a thin shell over :func:`vrcpilot.process.find_pids`:
its only contract is "exit 1 + empty stdout when no VRChat is running,
otherwise one PID per line on stdout (exit 0) in the order returned by
``find_pids``."

The project autouse ``_no_real_vrchat`` fixture pre-empties
``psutil.process_iter`` so every test below runs the negative path
without any mocking. Listing live PIDs requires either a real
``VRChat.exe`` process or stubbing psutil (banned by the new mocking
policy) -- both are deferred to the e2e suite.
"""

from __future__ import annotations

import pytest

from vrcpilot.cli import main


class TestPidNoVRChat:
    """``vrcpilot pid`` against a host with no VRChat running."""

    def test_exits_with_code_one(self):
        # ``find_pids()`` returns ``[]`` (autouse empty ``process_iter``),
        # so the CLI takes the "no running VRChat" branch.
        assert main(["pid"]) == 1

    def test_stdout_is_empty(self, capsys: pytest.CaptureFixture[str]):
        main(["pid"])
        assert capsys.readouterr().out == ""

    def test_stderr_is_empty(self, capsys: pytest.CaptureFixture[str]):
        # The "no PIDs" path is intentionally silent so callers can
        # branch on the exit code without filtering noise.
        main(["pid"])
        assert capsys.readouterr().err == ""
