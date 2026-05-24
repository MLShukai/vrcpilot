"""Tests for :mod:`vrcpilot.cli.linux_mic` (Linux-only).

``vrcpilot linux-mic`` manages the PipeWire null-sink that exposes a
virtual mic to VRChat. The three actions (``register`` / ``unregister``
/ ``status``) talk to ``pulsectl`` + ``soundcard`` + the on-disk
PipeWire config. Real success paths need a working PipeWire daemon,
which we do not bring up in unit tests -- those are deferred to e2e.

What we can cover here without a daemon:

* Argparse plumbing (action required, sub-options resolved).
* ``status`` always returns 0 and prints the documented stable
  vocabulary on stdout even when probes fail (probe errors land on
  stderr, not stdout).
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "linux":
    pytest.skip("vrcpilot.cli.linux_mic is Linux-only", allow_module_level=True)

from vrcpilot.cli import build_parser, main  # noqa: E402


class TestLinuxMicArgparse:
    def test_action_required(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["linux-mic"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_register_action(self):
        ns = build_parser().parse_args(["linux-mic", "register"])
        assert ns.action == "register"
        assert ns.no_runtime_load is False

    def test_register_no_runtime_load_flag(self):
        ns = build_parser().parse_args(["linux-mic", "register", "--no-runtime-load"])
        assert ns.no_runtime_load is True

    def test_unregister_action(self):
        ns = build_parser().parse_args(["linux-mic", "unregister"])
        assert ns.action == "unregister"

    def test_status_action(self):
        ns = build_parser().parse_args(["linux-mic", "status"])
        assert ns.action == "status"


class TestLinuxMicStatus:
    """``status`` returns 0 even when probes fail; stdout stays parseable.

    The contract is split-stream: stdout carries the answer with a fixed
    vocabulary (``present`` / ``absent`` / ``loaded`` / ``not loaded`` /
    ``unavailable`` / ``visible`` / ``not visible``), and any probe-side
    error lands on stderr as ``<channel>: error: <message>``.
    """

    def test_returns_zero(self, capsys: pytest.CaptureFixture[str]):
        # No PipeWire daemon on the test runner is fine -- status is
        # designed to surface ``unavailable`` rather than raise.
        assert main(["linux-mic", "status"]) == 0
        # Some stdout output is guaranteed (config / runtime / soundcard
        # lines); the precise content depends on host state.
        assert capsys.readouterr().out != ""

    def test_stdout_includes_config_line(self, capsys: pytest.CaptureFixture[str]):
        main(["linux-mic", "status"])
        stdout = capsys.readouterr().out
        # The "config: present|absent" prefix is part of the stable
        # vocabulary downstream scripts grep for.
        assert "config:" in stdout

    def test_stdout_includes_config_path(self, capsys: pytest.CaptureFixture[str]):
        main(["linux-mic", "status"])
        stdout = capsys.readouterr().out
        assert "config_path:" in stdout
