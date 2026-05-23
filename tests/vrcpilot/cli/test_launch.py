"""Tests for :mod:`vrcpilot.cli.launch`.

The CLI's only job is argv parsing and dispatch to
:func:`vrcpilot.process.launch`. We stub ``launch`` itself so the tests
never spawn a real subprocess, never poll for PIDs, and remain fast and
deterministic on every platform. Exception paths are exercised by
setting ``side_effect`` on the stub.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from vrcpilot.cli import main
from vrcpilot.process import (
    UmuLauncherNotFoundError,
    VRChatAlreadyRunningError,
    VRChatLauncherNotFoundError,
)
from vrcpilot.steam import SteamNotFoundError


@pytest.fixture
def fake_launch(mocker: MockerFixture) -> MagicMock:
    """Stub ``vrcpilot.cli.launch.launch`` so CLI tests do not actually spawn.

    Returns the mock so tests can assert call arguments. The mock's
    ``return_value`` is the PID that ``launch`` would have observed
    (set per-test via ``fake_launch.return_value = ...``).
    """
    mock = mocker.patch("vrcpilot.cli.launch.launch", return_value=12345, autospec=True)
    return mock


class TestLaunchCommand:
    def test_via_steam_forwarded(self, fake_launch: MagicMock) -> None:
        exit_code = main(["launch", "--via-steam"])
        assert exit_code == 0
        assert fake_launch.call_args.kwargs["via_steam"] is True

    def test_default_uses_direct_spawn(self, fake_launch: MagicMock) -> None:
        exit_code = main(["launch"])
        assert exit_code == 0
        assert fake_launch.call_args.kwargs["via_steam"] is False

    def test_app_id_forwarded(self, fake_launch: MagicMock) -> None:
        main(["launch", "--app-id", "999"])
        assert fake_launch.call_args.kwargs["app_id"] == 999

    def test_steam_path_forwarded(self, fake_launch: MagicMock, tmp_path: Path) -> None:
        steam_path = tmp_path / "steam.exe"
        main(["launch", "--steam-path", str(steam_path)])
        assert fake_launch.call_args.kwargs["steam_path"] == steam_path

    def test_vrchat_launcher_forwarded(
        self, fake_launch: MagicMock, tmp_path: Path
    ) -> None:
        launcher = tmp_path / "launch.exe"
        main(["launch", "--vrchat-launcher", str(launcher)])
        assert fake_launch.call_args.kwargs["vrchat_launcher"] == launcher

    def test_wineprefix_forwarded(self, fake_launch: MagicMock, tmp_path: Path) -> None:
        prefix = tmp_path / "prefix"
        main(["launch", "--wineprefix", str(prefix)])
        assert fake_launch.call_args.kwargs["wineprefix"] == prefix

    def test_proton_path_forwarded(
        self, fake_launch: MagicMock, tmp_path: Path
    ) -> None:
        proton = tmp_path / "proton"
        main(["launch", "--proton-path", str(proton)])
        assert fake_launch.call_args.kwargs["proton_path"] == proton

    def test_profile_forwarded(self, fake_launch: MagicMock) -> None:
        main(["launch", "--profile", "3"])
        assert fake_launch.call_args.kwargs["profile"] == 3

    def test_profile_zero_accepted(self, fake_launch: MagicMock) -> None:
        # 0 is the boundary value and must be accepted (non-negative).
        main(["launch", "--profile", "0"])
        assert fake_launch.call_args.kwargs["profile"] == 0

    def test_profile_negative_rejected_by_argparse(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            main(["launch", "--profile", "-1"])
        stderr = capsys.readouterr().err
        assert "non-negative" in stderr

    def test_no_vr_propagates(self, fake_launch: MagicMock) -> None:
        main(["launch", "--no-vr"])
        assert fake_launch.call_args.kwargs["no_vr"] is True

    def test_screen_dimensions_propagate(self, fake_launch: MagicMock) -> None:
        main(["launch", "--screen-width", "1920", "--screen-height", "1080"])
        kw = fake_launch.call_args.kwargs
        assert kw["screen_width"] == 1920
        assert kw["screen_height"] == 1080

    def test_osc_in_port_creates_config(self, fake_launch: MagicMock) -> None:
        main(["launch", "--osc-in-port", "9100"])
        osc = fake_launch.call_args.kwargs["osc"]
        assert osc is not None
        assert osc.in_port == 9100

    def test_osc_full_override(self, fake_launch: MagicMock) -> None:
        main(
            [
                "launch",
                "--osc-in-port",
                "9100",
                "--osc-out-ip",
                "1.2.3.4",
                "--osc-out-port",
                "9200",
            ]
        )
        osc = fake_launch.call_args.kwargs["osc"]
        assert osc is not None
        assert osc.in_port == 9100
        assert osc.out_ip == "1.2.3.4"
        assert osc.out_port == 9200

    def test_osc_out_options_ignored_without_in_port(
        self, fake_launch: MagicMock
    ) -> None:
        main(["launch", "--osc-out-ip", "1.2.3.4"])
        assert fake_launch.call_args.kwargs["osc"] is None

    def test_wait_timeout_forwarded(self, fake_launch: MagicMock) -> None:
        main(["launch", "--wait-timeout", "0.5"])
        assert fake_launch.call_args.kwargs["wait_timeout"] == 0.5


class TestLaunchExitCodes:
    def test_prints_pid_on_success(
        self, fake_launch: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_launch.return_value = 4242
        assert main(["launch"]) == 0
        assert capsys.readouterr().out.strip() == "4242"

    def test_exit_1_when_wait_times_out(
        self, fake_launch: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_launch.return_value = None
        assert main(["launch"]) == 1
        assert "did not start" in capsys.readouterr().err

    def test_exit_0_when_wait_skipped(self, fake_launch: MagicMock) -> None:
        fake_launch.return_value = None
        assert main(["launch", "--wait-timeout", "0"]) == 0

    def test_exit_0_when_wait_skipped_negative(self, fake_launch: MagicMock) -> None:
        # Lock the boundary: any <=0 value skips the wait.
        fake_launch.return_value = None
        assert main(["launch", "--wait-timeout", "-1"]) == 0

    def test_exit_2_on_steam_not_found(
        self, fake_launch: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_launch.side_effect = SteamNotFoundError("Steam not found")
        assert main(["launch", "--via-steam"]) == 2
        assert "Steam not found" in capsys.readouterr().err

    def test_exit_2_on_vrchat_launcher_not_found(
        self, fake_launch: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_launch.side_effect = VRChatLauncherNotFoundError("nope")
        assert main(["launch"]) == 2
        assert "nope" in capsys.readouterr().err

    def test_exit_2_on_umu_launcher_not_found(
        self, fake_launch: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_launch.side_effect = UmuLauncherNotFoundError("no umu-run")
        assert main(["launch"]) == 2
        assert "no umu-run" in capsys.readouterr().err

    def test_exit_2_on_value_error(
        self, fake_launch: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_launch.side_effect = ValueError("bad flag combo")
        assert main(["launch", "--via-steam", "--profile", "1"]) == 2
        assert "bad flag combo" in capsys.readouterr().err

    def test_exit_3_on_already_running(
        self, fake_launch: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_launch.side_effect = VRChatAlreadyRunningError("running")
        assert main(["launch", "--via-steam"]) == 3
        assert "running" in capsys.readouterr().err
