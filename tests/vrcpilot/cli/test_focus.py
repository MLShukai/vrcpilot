"""Tests for :mod:`vrcpilot.cli.focus`."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from vrcpilot.cli import main
from vrcpilot.process import VRChatMultipleInstancesError


class TestFocusCommand:
    def test_silent_on_success(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        # ``focus.run`` calls the locally imported ``focus`` window
        # function, so the right patch boundary is the binding inside
        # the submodule.
        mocker.patch("vrcpilot.cli.focus.focus", return_value=True)

        exit_code = main(["focus"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_stderr_on_failure(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        mocker.patch("vrcpilot.cli.focus.focus", return_value=False)

        exit_code = main(["focus"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "vrcpilot: could not focus VRChat\n"

    def test_passes_pid_to_api(self, mocker: MockerFixture):
        # ``--pid`` should be forwarded verbatim to ``focus()``.
        focus_stub = mocker.patch("vrcpilot.cli.focus.focus", return_value=True)

        exit_code = main(["focus", "--pid", "12345"])

        assert exit_code == 0
        focus_stub.assert_called_once_with(pid=12345)

    def test_no_pid_passes_none(self, mocker: MockerFixture):
        # When ``--pid`` is omitted, the API receives ``pid=None`` so
        # ``resolve_pid`` does the lookup.
        focus_stub = mocker.patch("vrcpilot.cli.focus.focus", return_value=True)

        exit_code = main(["focus"])

        assert exit_code == 0
        focus_stub.assert_called_once_with(pid=None)

    def test_multiple_instances_exits_with_diagnostic(
        self, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
    ):
        mocker.patch(
            "vrcpilot.cli.focus.focus",
            side_effect=VRChatMultipleInstancesError([1111, 2222]),
        )

        exit_code = main(["focus"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert (
            captured.err == "vrcpilot: multiple VRChat instances detected "
            "(PIDs: 1111 2222); pass --pid\n"
        )
