"""Tests for :mod:`vrcpilot.cli.unfocus`."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from vrcpilot.cli import main
from vrcpilot.process import VRChatMultipleInstancesError


class TestUnfocusCommand:
    def test_silent_on_success(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        # ``unfocus.run`` calls the locally imported ``unfocus`` window
        # function, so the right patch boundary is the binding inside
        # the submodule.
        mocker.patch("vrcpilot.cli.unfocus.unfocus", return_value=True)

        exit_code = main(["unfocus"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_stderr_on_failure(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        mocker.patch("vrcpilot.cli.unfocus.unfocus", return_value=False)

        exit_code = main(["unfocus"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "vrcpilot: could not unfocus VRChat\n"

    def test_passes_pid_to_api(self, mocker: MockerFixture):
        unfocus_stub = mocker.patch("vrcpilot.cli.unfocus.unfocus", return_value=True)

        exit_code = main(["unfocus", "--pid", "67890"])

        assert exit_code == 0
        unfocus_stub.assert_called_once_with(pid=67890)

    def test_no_pid_passes_none(self, mocker: MockerFixture):
        unfocus_stub = mocker.patch("vrcpilot.cli.unfocus.unfocus", return_value=True)

        exit_code = main(["unfocus"])

        assert exit_code == 0
        unfocus_stub.assert_called_once_with(pid=None)

    def test_multiple_instances_exits_with_diagnostic(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        mocker.patch(
            "vrcpilot.cli.unfocus.unfocus",
            side_effect=VRChatMultipleInstancesError([3333, 4444]),
        )

        exit_code = main(["unfocus"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert (
            captured.err == "vrcpilot: multiple VRChat instances detected "
            "(PIDs: 3333 4444); pass --pid\n"
        )
