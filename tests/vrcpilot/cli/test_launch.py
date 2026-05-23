"""Tests for :mod:`vrcpilot.cli.launch`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakePopen
from vrcpilot.cli import main
from vrcpilot.process import VRCHAT_STEAM_APP_ID


@pytest.fixture
def fake_popen(mocker: MockerFixture, tmp_path: Path) -> type[FakePopen]:
    """Patch ``subprocess.Popen`` so launch tests can record argv.

    Also stubs :func:`vrcpilot.steam.find_steam_executable` to honour
    any ``--steam-path`` override, falling back to a real file under
    ``tmp_path``. That single mock is unavoidable - the real lookup
    would touch the Windows registry or ``$PATH`` - but every other
    byte of the launch chain runs unmodified, including the dispatch
    on ``override is not None``.

    Class-level state is reset every test so ``last_argv`` reflects
    only this test's invocation.
    """
    FakePopen.reset()
    mocker.patch("vrcpilot.process.subprocess.Popen", FakePopen)
    steam_stub = tmp_path / "Steam.exe"
    steam_stub.write_bytes(b"")

    def _find(override: Path | None = None) -> Path:
        return override if override is not None else steam_stub

    mocker.patch("vrcpilot.steam.find_steam_executable", side_effect=_find)
    return FakePopen


@pytest.fixture
def fake_wait_for_pid(mocker: MockerFixture) -> MockerFixture:
    """Stub ``wait_for_pid`` so launch tests do not poll for real.

    The CLI no longer calls ``wait_for_pid`` directly; the polling now
    happens inside ``vrcpilot.process.launch``, so we patch the helper
    where it actually runs. Default return is ``12345`` so the happy
    path "saw a PID" branch runs by default. Tests that need a
    different value override the return via
    ``mocker.patch(..., return_value=...)`` directly.
    """
    mocker.patch("vrcpilot.process.wait_for_pid", return_value=12345)
    return mocker


class TestLaunchCommand:
    def test_uses_defaults(
        self, fake_popen: type[FakePopen], fake_wait_for_pid: MockerFixture
    ):
        del fake_wait_for_pid
        exit_code = main(["launch"])

        assert exit_code == 0
        assert fake_popen.last_argv is not None
        assert fake_popen.last_argv[1:] == ["-applaunch", str(VRCHAT_STEAM_APP_ID)]

    def test_prints_pid_on_success(
        self,
        fake_popen: type[FakePopen],
        fake_wait_for_pid: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_popen, fake_wait_for_pid
        exit_code = main(["launch"])

        assert exit_code == 0
        assert capsys.readouterr().out == "12345\n"

    def test_app_id_override(
        self, fake_popen: type[FakePopen], fake_wait_for_pid: MockerFixture
    ):
        del fake_wait_for_pid
        exit_code = main(["launch", "--app-id", "12345"])

        assert exit_code == 0
        assert fake_popen.last_argv is not None
        assert "-applaunch" in fake_popen.last_argv
        assert "12345" in fake_popen.last_argv

    def test_steam_path_override(
        self,
        fake_popen: type[FakePopen],
        fake_wait_for_pid: MockerFixture,
        tmp_path: Path,
    ):
        # ``fake_popen`` mocks ``find_steam_executable`` with a
        # pass-through ``side_effect`` that honours the ``override``
        # arg, so the user-supplied path flows all the way through to
        # ``Popen``.
        del fake_wait_for_pid
        override = tmp_path / "custom_steam.exe"

        exit_code = main(["launch", "--steam-path", str(override)])

        assert exit_code == 0
        assert fake_popen.last_argv is not None
        assert fake_popen.last_argv[0] == str(override)

    def test_reports_steam_not_found(self, capsys: pytest.CaptureFixture[str]):
        # Pass a path that does not exist - ``find_steam_executable``
        # raises ``SteamNotFoundError`` for real, no patching needed.
        steam_path = "/does/not/exist/Steam.exe"
        exit_code = main(["launch", "--steam-path", steam_path])

        assert exit_code == 2
        if sys.platform == "win32":
            assert steam_path.replace("/", "\\") in capsys.readouterr().err
        else:
            assert "/does/not/exist/Steam.exe" in capsys.readouterr().err

    def test_no_vr_flag_propagates(
        self, fake_popen: type[FakePopen], fake_wait_for_pid: MockerFixture
    ):
        del fake_wait_for_pid
        exit_code = main(["launch", "--no-vr"])

        assert exit_code == 0
        assert fake_popen.last_argv is not None
        assert "--no-vr" in fake_popen.last_argv

    def test_screen_dimensions_propagate(
        self, fake_popen: type[FakePopen], fake_wait_for_pid: MockerFixture
    ):
        del fake_wait_for_pid
        exit_code = main(["launch", "--screen-width", "1280", "--screen-height", "720"])

        assert exit_code == 0
        assert fake_popen.last_argv is not None
        assert "-screen-width" in fake_popen.last_argv
        assert "1280" in fake_popen.last_argv
        assert "-screen-height" in fake_popen.last_argv
        assert "720" in fake_popen.last_argv

    def test_osc_in_port_creates_config(
        self, fake_popen: type[FakePopen], fake_wait_for_pid: MockerFixture
    ):
        del fake_wait_for_pid
        exit_code = main(["launch", "--osc-in-port", "9000"])

        assert exit_code == 0
        assert fake_popen.last_argv is not None
        assert "--osc=9000:127.0.0.1:9001" in fake_popen.last_argv

    def test_osc_full_override(
        self, fake_popen: type[FakePopen], fake_wait_for_pid: MockerFixture
    ):
        del fake_wait_for_pid
        exit_code = main(
            [
                "launch",
                "--osc-in-port",
                "10000",
                "--osc-out-ip",
                "192.168.1.10",
                "--osc-out-port",
                "10001",
            ]
        )

        assert exit_code == 0
        assert fake_popen.last_argv is not None
        assert "--osc=10000:192.168.1.10:10001" in fake_popen.last_argv

    def test_osc_out_options_ignored_without_in_port(
        self, fake_popen: type[FakePopen], fake_wait_for_pid: MockerFixture
    ):
        del fake_wait_for_pid
        exit_code = main(["launch", "--osc-out-ip", "192.168.1.10"])

        assert exit_code == 0
        assert fake_popen.last_argv is not None
        # No --osc=... token because --osc-in-port was not given.
        assert not any(token.startswith("--osc=") for token in fake_popen.last_argv)


class TestLaunchWaitTimeout:
    def test_wait_timeout_zero_skips_wait(
        self,
        fake_popen: type[FakePopen],
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_popen
        wait_mock = mocker.patch("vrcpilot.process.wait_for_pid")

        exit_code = main(["launch", "--wait-timeout", "0"])

        assert exit_code == 0
        assert capsys.readouterr().out == ""
        wait_mock.assert_not_called()

    def test_negative_wait_timeout_skips_wait(
        self,
        fake_popen: type[FakePopen],
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        # The plan says "any value <= 0" skips the wait; lock that in
        # explicitly so the boundary stays inclusive of zero.
        del fake_popen
        wait_mock = mocker.patch("vrcpilot.process.wait_for_pid")

        exit_code = main(["launch", "--wait-timeout", "-1"])

        assert exit_code == 0
        assert capsys.readouterr().out == ""
        wait_mock.assert_not_called()

    def test_pid_observed_within_timeout(
        self,
        fake_popen: type[FakePopen],
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_popen
        mocker.patch("vrcpilot.process.wait_for_pid", return_value=54321)

        exit_code = main(["launch", "--wait-timeout", "10"])

        assert exit_code == 0
        assert capsys.readouterr().out == "54321\n"

    def test_timeout_returns_one_with_stderr(
        self,
        fake_popen: type[FakePopen],
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_popen
        mocker.patch("vrcpilot.process.wait_for_pid", return_value=None)

        exit_code = main(["launch", "--wait-timeout", "2.5"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: VRChat did not start within 2.5s" in captured.err

    def test_wait_timeout_zero_silent_when_launch_returns_none(
        self,
        fake_popen: type[FakePopen],
        capsys: pytest.CaptureFixture[str],
    ):
        # No wait helper patch: with --wait-timeout 0, launch() returns
        # None up-front (no polling) and the CLI must exit 0 silently.
        del fake_popen
        exit_code = main(["launch", "--wait-timeout", "0"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_wait_timeout_forwarded_to_helper(
        self,
        fake_popen: type[FakePopen],
        mocker: MockerFixture,
    ):
        del fake_popen
        wait_mock = mocker.patch("vrcpilot.process.wait_for_pid", return_value=99999)

        exit_code = main(["launch", "--wait-timeout", "7"])

        assert exit_code == 0
        wait_mock.assert_called_once_with(timeout=7.0, interval=1.0)
