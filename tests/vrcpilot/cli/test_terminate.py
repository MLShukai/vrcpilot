"""Tests for :mod:`vrcpilot.cli.terminate`."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeProcess
from vrcpilot.cli import main
from vrcpilot.process import VRCHAT_PROCESS_NAME


@pytest.fixture
def stub_wait_procs(mocker: MockerFixture) -> None:
    """Short-circuit ``psutil.wait_procs`` for fake-process inputs.

    The real :func:`psutil.wait_procs` type-checks its first arg as a
    list of :class:`psutil.Process`; handing it ``FakeProcess``
    instances raises. The CLI flow does not care about the wait
    result, so a ``([], [])`` return is enough to keep the run
    end-to-end while bypassing the type check.
    """
    mocker.patch("vrcpilot.process.psutil.wait_procs", return_value=([], []))


class TestTerminateCommand:
    def test_prints_killed_pids(
        self,
        mocker: MockerFixture,
        stub_wait_procs: None,
        capsys: pytest.CaptureFixture[str],
    ):
        del stub_wait_procs
        mocker.patch(
            "vrcpilot.process.psutil.process_iter",
            return_value=[FakeProcess(name=VRCHAT_PROCESS_NAME, pid=4242)],
        )

        exit_code = main(["terminate"])

        assert exit_code == 0
        assert capsys.readouterr().out == "4242\n"

    def test_silent_when_nothing_running(self, capsys: pytest.CaptureFixture[str]):
        # Autouse empty default makes this a real, mock-free run of
        # the negative path.
        exit_code = main(["terminate"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    @pytest.mark.parametrize(
        "running_pids",
        [
            [],
            [777],
            [101, 202, 303],
        ],
    )
    def test_exit_code_zero_in_both_cases(
        self,
        running_pids: list[int],
        mocker: MockerFixture,
        stub_wait_procs: None,
    ):
        del stub_wait_procs
        mocker.patch(
            "vrcpilot.process.psutil.process_iter",
            return_value=[
                FakeProcess(name=VRCHAT_PROCESS_NAME, pid=pid) for pid in running_pids
            ],
        )

        exit_code = main(["terminate"])

        assert exit_code == 0

    def test_multiple_killed_pids_each_on_own_line(
        self,
        mocker: MockerFixture,
        stub_wait_procs: None,
        capsys: pytest.CaptureFixture[str],
    ):
        del stub_wait_procs
        mocker.patch(
            "vrcpilot.process.psutil.process_iter",
            return_value=[
                FakeProcess(name=VRCHAT_PROCESS_NAME, pid=111),
                FakeProcess(name=VRCHAT_PROCESS_NAME, pid=222),
                FakeProcess(name=VRCHAT_PROCESS_NAME, pid=333),
            ],
        )

        exit_code = main(["terminate"])

        assert exit_code == 0
        assert capsys.readouterr().out.splitlines() == ["111", "222", "333"]


class TestTerminatePositionalPids:
    """``terminate`` accepts variadic positional PIDs to target subsets."""

    def test_kills_all_when_no_positional_args(
        self, mocker: MockerFixture, stub_wait_procs: None
    ):
        # With no positional args the CLI forwards an empty tuple to
        # ``terminate()``, which falls back to "kill every VRChat".
        del stub_wait_procs
        spy = mocker.patch("vrcpilot.cli.terminate.terminate", return_value=[111, 222])

        exit_code = main(["terminate"])

        assert exit_code == 0
        spy.assert_called_once_with()

    def test_kills_specified_pid_when_one_positional(
        self, mocker: MockerFixture, stub_wait_procs: None
    ):
        del stub_wait_procs
        spy = mocker.patch("vrcpilot.cli.terminate.terminate", return_value=[4242])

        exit_code = main(["terminate", "4242"])

        assert exit_code == 0
        spy.assert_called_once_with(4242)

    def test_kills_multiple_pids_when_multiple_positionals(
        self,
        mocker: MockerFixture,
        stub_wait_procs: None,
        capsys: pytest.CaptureFixture[str],
    ):
        del stub_wait_procs
        spy = mocker.patch(
            "vrcpilot.cli.terminate.terminate", return_value=[111, 222, 333]
        )

        exit_code = main(["terminate", "111", "222", "333"])

        assert exit_code == 0
        spy.assert_called_once_with(111, 222, 333)
        # The CLI prints whatever ``terminate`` returned, one per line.
        assert capsys.readouterr().out.splitlines() == ["111", "222", "333"]

    def test_value_error_exits_1(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        # ``process.terminate`` raises ``ValueError`` when an explicit
        # PID exists but is not a VRChat process; the CLI maps that to
        # exit 1 + a ``vrcpilot: ...`` stderr diagnostic.
        mocker.patch(
            "vrcpilot.cli.terminate.terminate",
            side_effect=ValueError("PID 1234 is not a VRChat process (name='cat')"),
        )

        exit_code = main(["terminate", "1234"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert (
            "vrcpilot: PID 1234 is not a VRChat process (name='cat')\n" in captured.err
        )

    def test_rejects_non_int_positional(self, capsys: pytest.CaptureFixture[str]):
        # ``argparse`` rejects non-int positionals up front (``type=int``).
        with pytest.raises(SystemExit) as excinfo:
            main(["terminate", "not-an-int"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""
