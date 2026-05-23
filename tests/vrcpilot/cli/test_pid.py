"""Tests for :mod:`vrcpilot.cli.pid`."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeProcess
from vrcpilot.cli import main
from vrcpilot.process import VRCHAT_PROCESS_NAME


class TestPidCommand:
    def test_prints_each_pid_on_separate_line(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        mocker.patch(
            "vrcpilot.process.pid.psutil.process_iter",
            return_value=[
                FakeProcess(name=VRCHAT_PROCESS_NAME, pid=111),
                FakeProcess(name=VRCHAT_PROCESS_NAME, pid=222),
            ],
        )

        exit_code = main(["pid"])

        assert exit_code == 0
        out_lines = capsys.readouterr().out.splitlines()
        assert out_lines == ["111", "222"]

    def test_exit_code_when_running(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        mocker.patch(
            "vrcpilot.process.pid.psutil.process_iter",
            return_value=[FakeProcess(name=VRCHAT_PROCESS_NAME, pid=12345)],
        )

        exit_code = main(["pid"])

        assert exit_code == 0
        assert capsys.readouterr().out == "12345\n"

    def test_exit_code_when_absent(self, capsys: pytest.CaptureFixture[str]):
        # The autouse conftest fixture empties ``process_iter`` so this
        # is a real, mock-free run of the negative path.
        exit_code = main(["pid"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_no_stdout_when_absent(self, capsys: pytest.CaptureFixture[str]):
        exit_code = main(["pid"])

        assert exit_code == 1
        assert capsys.readouterr().out == ""

    def test_multiple_pids_in_iter_order(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        # Order in stdout must mirror ``process_iter`` order so callers
        # can rely on it staying consistent with ``find_pids()``.
        mocker.patch(
            "vrcpilot.process.pid.psutil.process_iter",
            return_value=[
                FakeProcess(name=VRCHAT_PROCESS_NAME, pid=300),
                FakeProcess(name="other.exe", pid=999),
                FakeProcess(name=VRCHAT_PROCESS_NAME, pid=100),
                FakeProcess(name=VRCHAT_PROCESS_NAME, pid=200),
            ],
        )

        exit_code = main(["pid"])

        assert exit_code == 0
        assert capsys.readouterr().out.splitlines() == ["300", "100", "200"]
