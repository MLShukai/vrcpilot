"""Tests for :mod:`vrcpilot.process`."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import psutil
import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakePopen, FakeProcess
from tests.helpers import only_linux, only_windows
from vrcpilot.process import (
    VRCHAT_PROCESS_NAME,
    VRCHAT_STEAM_APP_ID,
    OscConfig,
    build_launch_command,
    build_vrchat_launch_args,
    find_pid,
    find_pids,
    launch,
    terminate,
    wait_for_no_pid,
    wait_for_pid,
)


@pytest.fixture
def fake_popen(monkeypatch: pytest.MonkeyPatch) -> type[FakePopen]:
    """Replace ``subprocess.Popen`` with :class:`FakePopen` for the test.

    The class itself is swapped in (not an instance), so each
    ``Popen(...)`` call inside production code constructs a real
    ``FakePopen`` and we can introspect ``last_argv`` / ``last_kwargs``.
    """
    FakePopen.reset()
    monkeypatch.setattr("vrcpilot.process.subprocess.Popen", FakePopen)
    return FakePopen


def _patch_steam_path(mocker: MockerFixture, steam: Path) -> None:
    """Stub out the Steam binary discovery so ``launch()`` can be exercised."""
    mocker.patch("vrcpilot.steam.find_steam_executable", return_value=steam)


def _process_iter_returning(mocker: MockerFixture, *procs: FakeProcess) -> None:
    """Override the autouse empty-iterator default with the given fakes."""
    mocker.patch(
        "vrcpilot.process.psutil.process_iter",
        return_value=list(procs),
    )


class TestOscConfig:
    def test_to_launch_arg_default(self):
        assert OscConfig().to_launch_arg() == "--osc=9000:127.0.0.1:9001"

    @pytest.mark.parametrize(
        ("in_port", "out_ip", "out_port", "expected"),
        [
            (9000, "127.0.0.1", 9001, "--osc=9000:127.0.0.1:9001"),
            (10000, "192.168.1.10", 10001, "--osc=10000:192.168.1.10:10001"),
            (1234, "0.0.0.0", 5678, "--osc=1234:0.0.0.0:5678"),
        ],
    )
    def test_to_launch_arg_custom(
        self, in_port: int, out_ip: str, out_port: int, expected: str
    ):
        cfg = OscConfig(in_port=in_port, out_ip=out_ip, out_port=out_port)

        assert cfg.to_launch_arg() == expected

    def test_is_frozen(self):
        cfg = OscConfig()

        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.in_port = 1234  # type: ignore[misc]


class TestBuildVrchatLaunchArgs:
    def test_no_args_returns_empty(self):
        assert build_vrchat_launch_args() == []

    def test_no_vr(self):
        assert build_vrchat_launch_args(no_vr=True) == ["--no-vr"]

    @pytest.mark.parametrize(
        ("width", "height", "expected"),
        [
            (1280, None, ["-screen-width", "1280"]),
            (None, 720, ["-screen-height", "720"]),
            (
                1280,
                720,
                ["-screen-width", "1280", "-screen-height", "720"],
            ),
        ],
    )
    def test_screen_dimensions(
        self, width: int | None, height: int | None, expected: list[str]
    ):
        result = build_vrchat_launch_args(screen_width=width, screen_height=height)

        assert result == expected

    def test_osc(self):
        result = build_vrchat_launch_args(osc=OscConfig(in_port=9000))

        assert result == ["--osc=9000:127.0.0.1:9001"]

    def test_extra_args_appended(self):
        result = build_vrchat_launch_args(extra_args=["--enable-debug-gui"])

        assert result == ["--enable-debug-gui"]

    def test_combined_order(self):
        result = build_vrchat_launch_args(
            no_vr=True,
            screen_width=1280,
            screen_height=720,
            osc=OscConfig(),
            extra_args=["--enable-debug-gui", "--profile=2"],
        )

        assert result == [
            "--no-vr",
            "-screen-width",
            "1280",
            "-screen-height",
            "720",
            "--osc=9000:127.0.0.1:9001",
            "--enable-debug-gui",
            "--profile=2",
        ]


class TestBuildLaunchCommand:
    def test_basic(self):
        steam = Path("/usr/bin/steam")

        result = build_launch_command(steam, 438100)

        assert result == [str(steam), "-applaunch", "438100"]

    @pytest.mark.parametrize("app_id", [438100, 440, 1])
    def test_app_id_stringified(self, app_id: int):
        result = build_launch_command(Path("/usr/bin/steam"), app_id)

        assert result[2] == str(app_id)

    def test_default_app_id(self):
        result = build_launch_command(Path("/usr/bin/steam"))

        assert result[2] == str(VRCHAT_STEAM_APP_ID)

    def test_appends_vrchat_args(self):
        steam = Path("/usr/bin/steam")

        result = build_launch_command(
            steam, 438100, vrchat_args=["--no-vr", "-screen-width", "1280"]
        )

        assert result == [
            str(steam),
            "-applaunch",
            "438100",
            "--no-vr",
            "-screen-width",
            "1280",
        ]

    def test_no_vrchat_args_returns_legacy_shape(self):
        steam = Path("/usr/bin/steam")

        result = build_launch_command(steam, 438100, vrchat_args=None)

        assert result == [str(steam), "-applaunch", "438100"]


class TestLaunch:
    """Cross-platform argv assembly is the same shape on every host.

    All tests pass ``wait_timeout=0`` to skip the post-spawn PID poll;
    the wait behaviour itself is exercised in :class:`TestLaunchWait`.
    """

    def test_invokes_popen_with_default_argv(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        steam = Path("/usr/bin/steam")
        _patch_steam_path(mocker, steam)

        launch(wait_timeout=0)

        assert fake_popen.last_argv == [str(steam), "-applaunch", "438100"]

    def test_propagates_steam_path_override(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        override = Path("/custom/steam")
        _patch_steam_path(mocker, override)

        launch(steam_path=override, wait_timeout=0)

        assert fake_popen.last_argv is not None
        assert fake_popen.last_argv[0] == str(override)

    def test_app_id_override(self, mocker: MockerFixture, fake_popen: type[FakePopen]):
        steam = Path("/usr/bin/steam")
        _patch_steam_path(mocker, steam)

        launch(app_id=440, wait_timeout=0)

        assert fake_popen.last_argv == [str(steam), "-applaunch", "440"]

    def test_passes_no_vr_to_argv(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        steam = Path("/usr/bin/steam")
        _patch_steam_path(mocker, steam)

        launch(no_vr=True, wait_timeout=0)

        assert fake_popen.last_argv is not None
        assert "--no-vr" in fake_popen.last_argv

    def test_passes_osc_to_argv(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        steam = Path("/usr/bin/steam")
        _patch_steam_path(mocker, steam)

        launch(osc=OscConfig(in_port=9000), wait_timeout=0)

        assert fake_popen.last_argv is not None
        assert "--osc=9000:127.0.0.1:9001" in fake_popen.last_argv

    @only_windows
    def test_uses_new_process_group_on_windows(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        _patch_steam_path(mocker, Path("C:/Steam/Steam.exe"))

        launch(wait_timeout=0)

        assert "creationflags" in fake_popen.last_kwargs
        assert "start_new_session" not in fake_popen.last_kwargs

    @only_linux
    def test_uses_new_session_on_linux(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        _patch_steam_path(mocker, Path("/usr/bin/steam"))

        launch(wait_timeout=0)

        assert fake_popen.last_kwargs.get("start_new_session") is True
        assert "creationflags" not in fake_popen.last_kwargs


class TestLaunchWait:
    """The post-spawn ``wait_for_pid`` integration in :func:`launch`."""

    def test_wait_timeout_zero_returns_none_without_polling(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        del fake_popen
        _patch_steam_path(mocker, Path("/usr/bin/steam"))
        wait_spy = mocker.patch("vrcpilot.process.wait_for_pid")

        result = launch(wait_timeout=0)

        assert result is None
        wait_spy.assert_not_called()

    def test_negative_wait_timeout_returns_none_without_polling(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        del fake_popen
        _patch_steam_path(mocker, Path("/usr/bin/steam"))
        wait_spy = mocker.patch("vrcpilot.process.wait_for_pid")

        result = launch(wait_timeout=-1.0)

        assert result is None
        wait_spy.assert_not_called()

    def test_returns_pid_when_observed_within_window(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        del fake_popen
        _patch_steam_path(mocker, Path("/usr/bin/steam"))
        _process_iter_returning(mocker, FakeProcess(name=VRCHAT_PROCESS_NAME, pid=4242))

        result = launch(wait_timeout=5.0, wait_interval=0.01)

        assert result == 4242

    def test_returns_none_when_pid_never_appears(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        del fake_popen
        _patch_steam_path(mocker, Path("/usr/bin/steam"))
        # autouse fixture leaves process_iter empty -> find_pid is None.
        # Tiny timeout/interval to keep the wall-clock loop short.
        result = launch(wait_timeout=0.05, wait_interval=0.01)

        assert result is None

    def test_forwards_timeout_and_interval_to_wait_for_pid(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        del fake_popen
        _patch_steam_path(mocker, Path("/usr/bin/steam"))
        wait_spy = mocker.patch("vrcpilot.process.wait_for_pid", return_value=12345)

        result = launch(wait_timeout=7.0, wait_interval=0.5)

        assert result == 12345
        wait_spy.assert_called_once_with(timeout=7.0, interval=0.5)


class TestFindPid:
    def test_returns_pid_when_running(self, mocker: MockerFixture):
        _process_iter_returning(mocker, FakeProcess(name=VRCHAT_PROCESS_NAME, pid=4242))

        assert find_pid() == 4242

    def test_returns_none_when_not_running(self):
        # autouse fixture already empties ``process_iter``; no setup needed.
        assert find_pid() is None

    def test_ignores_other_processes(self, mocker: MockerFixture):
        _process_iter_returning(mocker, FakeProcess(name="explorer.exe", pid=1))

        assert find_pid() is None

    def test_returns_first_when_multiple_match(self, mocker: MockerFixture):
        _process_iter_returning(
            mocker,
            FakeProcess(name=VRCHAT_PROCESS_NAME, pid=111),
            FakeProcess(name=VRCHAT_PROCESS_NAME, pid=222),
        )

        assert find_pid() == 111


class TestFindPids:
    def test_returns_empty_when_not_running(self):
        # autouse fixture already empties ``process_iter``; no setup needed.
        assert find_pids() == []

    def test_returns_single_match(self, mocker: MockerFixture):
        _process_iter_returning(mocker, FakeProcess(name=VRCHAT_PROCESS_NAME, pid=4242))

        assert find_pids() == [4242]

    def test_returns_all_matches_in_iter_order(self, mocker: MockerFixture):
        _process_iter_returning(
            mocker,
            FakeProcess(name=VRCHAT_PROCESS_NAME, pid=111),
            FakeProcess(name="explorer.exe", pid=222),
            FakeProcess(name=VRCHAT_PROCESS_NAME, pid=333),
        )

        assert find_pids() == [111, 333]

    def test_ignores_other_processes(self, mocker: MockerFixture):
        _process_iter_returning(mocker, FakeProcess(name="explorer.exe", pid=1))

        assert find_pids() == []


class TestWaitForPid:
    def test_returns_immediately_when_pid_exists(self, mocker: MockerFixture):
        _process_iter_returning(mocker, FakeProcess(name=VRCHAT_PROCESS_NAME, pid=42))
        # Sleep should never be called when the pid is already there.
        sleep_spy = mocker.patch("vrcpilot.process.time.sleep")

        result = wait_for_pid(timeout=5.0, interval=1.0)

        assert result == 42
        assert sleep_spy.call_count == 0

    def test_returns_none_on_timeout(self, mocker: MockerFixture):
        # autouse fixture leaves ``process_iter`` empty -> find_pid is None.
        # Use a tiny timeout/interval so the real wall-clock loop exits
        # within milliseconds without any monkeypatching of time.
        result = wait_for_pid(timeout=0.05, interval=0.01)

        assert result is None

    def test_uses_module_defaults(self):
        # Sanity: defaults match the documented constants.
        from vrcpilot.process import PID_WAIT_INTERVAL, PID_WAIT_TIMEOUT

        defaults = wait_for_pid.__defaults__
        assert defaults == (PID_WAIT_TIMEOUT, PID_WAIT_INTERVAL)


class TestWaitForNoPid:
    def test_returns_true_immediately_when_absent(self, mocker: MockerFixture):
        # autouse fixture: process_iter is empty -> find_pid is None.
        sleep_spy = mocker.patch("vrcpilot.process.time.sleep")

        result = wait_for_no_pid(timeout=5.0, interval=1.0)

        assert result is True
        assert sleep_spy.call_count == 0

    def test_returns_false_on_timeout(self, mocker: MockerFixture):
        _process_iter_returning(mocker, FakeProcess(name=VRCHAT_PROCESS_NAME))

        result = wait_for_no_pid(timeout=0.05, interval=0.01)

        assert result is False

    def test_uses_module_defaults(self):
        from vrcpilot.process import PID_WAIT_INTERVAL, PID_WAIT_TIMEOUT

        defaults = wait_for_no_pid.__defaults__
        assert defaults == (PID_WAIT_TIMEOUT, PID_WAIT_INTERVAL)


class TestTerminate:
    def test_kills_matching_process(self, mocker: MockerFixture):
        proc = FakeProcess(name=VRCHAT_PROCESS_NAME, pid=4242)
        _process_iter_returning(mocker, proc)
        mocker.patch("vrcpilot.process.psutil.wait_procs")

        result = terminate()

        assert result == [4242]
        assert proc.kill_calls == 1

    def test_returns_empty_list_when_not_running(self, mocker: MockerFixture):
        _process_iter_returning(mocker, FakeProcess(name="explorer.exe"))
        mocker.patch("vrcpilot.process.psutil.wait_procs")

        result = terminate()

        assert result == []

    def test_kills_all_matching(self, mocker: MockerFixture):
        p1 = FakeProcess(name=VRCHAT_PROCESS_NAME, pid=10)
        p2 = FakeProcess(name=VRCHAT_PROCESS_NAME, pid=20)
        other = FakeProcess(name="explorer.exe", pid=30)
        _process_iter_returning(mocker, p1, other, p2)
        mocker.patch("vrcpilot.process.psutil.wait_procs")

        result = terminate()

        assert result == [10, 20]
        assert p1.kill_calls == 1
        assert p2.kill_calls == 1
        assert other.kill_calls == 0

    def test_swallows_no_such_process(self, mocker: MockerFixture):
        proc = FakeProcess(
            name=VRCHAT_PROCESS_NAME,
            pid=9999,
            kill_raises=psutil.NoSuchProcess(pid=9999),
        )
        _process_iter_returning(mocker, proc)
        mocker.patch("vrcpilot.process.psutil.wait_procs")

        result = terminate()

        assert result == [9999]
