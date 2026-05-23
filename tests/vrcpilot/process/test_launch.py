"""Tests for :mod:`vrcpilot.process.launch`.

The launch flow has two modes:

- direct-spawn (default): ``launch.exe`` -> ``subprocess.Popen``, with
  ``umu-run`` prepended on Linux. PID is observed via the pre/post diff
  on :func:`find_pids`.
- ``via_steam=True``: legacy ``steam.exe -applaunch <app_id>`` flow; refuses
  to spawn when VRChat is already running.

All argv-shape assertions go through :class:`FakePopen` so production code
never actually fork+execs.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakePopen, FakeProcess
from vrcpilot.process import (
    VRCHAT_PROCESS_NAME,
    VRCHAT_STEAM_APP_ID,
    OscConfig,
    VRChatAlreadyRunningError,
    launch,
)
from vrcpilot.process.launch import build_vrchat_launch_args, validate_launch_args


@pytest.fixture(autouse=True)
def _bypass_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub Linux preflight for the argv/env shape tests.

    Real preflight inspects host state (DISPLAY env, running Steam process)
    which is irrelevant to argv-shape assertions and would otherwise force
    every test in this module to set up DISPLAY or stub psutil. The dedicated
    ``TestPreflightLinuxEnvironment`` class in
    :mod:`tests.vrcpilot.process.test_linux` exercises the real implementation
    in isolation.

    ``launch()`` does a deferred ``from .linux import preflight_linux_environment``
    only on Linux, so the bypass only needs to attach on Linux. On Windows
    runs, ``launch()`` never imports the module and this fixture is a no-op.
    """
    if sys.platform != "linux":
        return
    import vrcpilot.process.linux as linux_mod

    monkeypatch.setattr(
        linux_mod, "preflight_linux_environment", lambda *, via_steam: None
    )


@pytest.fixture
def fake_popen(monkeypatch: pytest.MonkeyPatch) -> type[FakePopen]:
    """Replace ``subprocess.Popen`` for the launch module's call site.

    ``vrcpilot.process.launch`` (the submodule) is shadowed in the
    package namespace by the re-exported :func:`launch` function, so
    neither ``monkeypatch.setattr("vrcpilot.process.launch.subprocess.Popen", ...)``
    nor ``import vrcpilot.process.launch as ...`` reaches the module
    object. Look it up directly via ``sys.modules`` and swap the entire
    ``subprocess`` attribute on that module for a proxy that exposes
    just the symbols ``launch()`` needs (``Popen``, ``DEVNULL`` and the
    Windows-only ``CREATE_NEW_PROCESS_GROUP``). The proxy isolates the
    change to the launch site without poisoning the singleton
    ``subprocess`` module in ``sys.modules``.
    """
    FakePopen.reset()

    launch_mod = sys.modules["vrcpilot.process.launch"]
    real_subprocess = launch_mod.subprocess

    class _Proxy:
        Popen = FakePopen
        DEVNULL = real_subprocess.DEVNULL
        # ``CREATE_NEW_PROCESS_GROUP`` is Windows-only on the real
        # ``subprocess`` module. Provide a placeholder constant so the
        # platform-monkeypatched Windows tests can build the kwargs dict
        # without an ``AttributeError`` on POSIX runners.
        CREATE_NEW_PROCESS_GROUP = getattr(
            real_subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
        )

    monkeypatch.setattr(launch_mod, "subprocess", _Proxy)
    return FakePopen


def _patch_steam_path(mocker: MockerFixture, steam: Path) -> None:
    """Stub Steam discovery so ``via_steam=True`` paths can be exercised."""
    mocker.patch("vrcpilot.steam.find_steam_executable", return_value=steam)


def _patch_launcher(mocker: MockerFixture, launcher: Path) -> None:
    """Stub ``launch.exe`` discovery for the direct-spawn paths."""
    mocker.patch(
        "vrcpilot.process.executable.find_vrchat_launcher",
        return_value=launcher,
    )


def _patch_umu(mocker: MockerFixture, umu: Path) -> None:
    """Stub ``umu-run`` discovery for Linux direct-spawn."""
    mocker.patch(
        "vrcpilot.process.linux.find_umu_launcher",
        return_value=umu,
    )


def _process_iter_returning(mocker: MockerFixture, *procs: FakeProcess) -> None:
    """Override the autouse empty-iterator default with the given fakes."""
    mocker.patch(
        "vrcpilot.process.psutil.process_iter",
        return_value=list(procs),
    )


@pytest.fixture
def linux_direct_spawn(
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
    tmp_path: Path,
) -> tuple[Path, Path]:
    """One-stop Linux direct-spawn setup.

    Patches ``sys.platform`` to ``"linux"``, plants fake ``launch.exe`` and
    ``umu-run`` files under ``tmp_path``, and stubs both discovery helpers
    to point at them. Returns ``(launcher, umu_run)`` so tests that need
    the concrete paths (e.g. for argv assertions) can read them back.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    launcher = tmp_path / "launch.exe"
    launcher.write_bytes(b"")
    umu = tmp_path / "umu-run"
    umu.write_bytes(b"")
    _patch_launcher(mocker, launcher)
    _patch_umu(mocker, umu)
    return launcher, umu


class TestBuildVrchatLaunchArgs:
    def test_profile_emits_single_equals_token(self):
        # VRChat's --profile is a single =-delimited token, not a pair of
        # tokens. The exact spelling matters: "--profile=3", not
        # ["--profile", "3"].
        args = build_vrchat_launch_args(profile=3)
        assert "--profile=3" in args

    def test_profile_none_does_not_emit_flag(self):
        args = build_vrchat_launch_args(profile=None)
        assert not any(a.startswith("--profile") for a in args)


class TestValidateLaunchArgs:
    def test_accepts_defaults(self):
        # Should not raise.
        validate_launch_args(
            via_steam=False, wineprefix=None, proton_path=None, profile=None
        )

    def test_accepts_via_steam_alone(self):
        validate_launch_args(
            via_steam=True, wineprefix=None, proton_path=None, profile=None
        )

    def test_negative_profile_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            validate_launch_args(
                via_steam=False, wineprefix=None, proton_path=None, profile=-1
            )

    def test_zero_profile_allowed(self):
        validate_launch_args(
            via_steam=False, wineprefix=None, proton_path=None, profile=0
        )

    def test_via_steam_with_wineprefix_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="direct-spawn"):
            validate_launch_args(
                via_steam=True,
                wineprefix=tmp_path,
                proton_path=None,
                profile=None,
            )

    def test_via_steam_with_proton_path_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="direct-spawn"):
            validate_launch_args(
                via_steam=True,
                wineprefix=None,
                proton_path=tmp_path,
                profile=None,
            )

    def test_via_steam_with_profile_raises(self):
        with pytest.raises(ValueError, match="direct-spawn"):
            validate_launch_args(
                via_steam=True, wineprefix=None, proton_path=None, profile=2
            )

    def test_windows_with_wineprefix_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr(sys, "platform", "win32")
        with pytest.raises(ValueError, match="Linux-only"):
            validate_launch_args(
                via_steam=False,
                wineprefix=tmp_path,
                proton_path=None,
                profile=None,
            )

    def test_windows_with_profile_accepted(self, monkeypatch: pytest.MonkeyPatch):
        # profile is platform-agnostic — Windows must accept it so VRChat's
        # --profile=N argv (separates SaveData/cache) can be forwarded.
        monkeypatch.setattr(sys, "platform", "win32")
        validate_launch_args(
            via_steam=False, wineprefix=None, proton_path=None, profile=2
        )

    def test_windows_with_proton_path_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr(sys, "platform", "win32")
        with pytest.raises(ValueError, match="Linux-only"):
            validate_launch_args(
                via_steam=False,
                wineprefix=None,
                proton_path=tmp_path,
                profile=None,
            )


class TestProcessLinuxModuleGuard:
    """``vrcpilot.process.linux`` is Linux-only and must reject non-Linux
    import."""

    def test_reimport_raises_on_non_linux(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the module was already loaded (Linux runs), reload under a
        # patched ``sys.platform`` should hit the guard. On Windows runs
        # the module was never imported, so we import it for the first
        # time under the patch.
        monkeypatch.setattr(sys, "platform", "win32")
        if "vrcpilot.process.linux" in sys.modules:
            linux_mod = sys.modules["vrcpilot.process.linux"]
            with pytest.raises(ImportError, match="Linux-only"):
                importlib.reload(linux_mod)
        else:
            with pytest.raises(ImportError, match="Linux-only"):
                importlib.import_module("vrcpilot.process.linux")


class TestLaunchViaSteam:
    """The ``via_steam=True`` (legacy) launch path."""

    def test_uses_steam_executable(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        steam = Path("/usr/bin/steam")
        _patch_steam_path(mocker, steam)

        launch(via_steam=True, wait_timeout=0)

        assert fake_popen.last_argv == [str(steam), "-applaunch", "438100"]

    def test_propagates_steam_path_override(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        override = Path("/custom/steam")
        _patch_steam_path(mocker, override)

        launch(via_steam=True, steam_path=override, wait_timeout=0)

        assert fake_popen.last_argv is not None
        assert fake_popen.last_argv[0] == str(override)

    def test_app_id_override(self, mocker: MockerFixture, fake_popen: type[FakePopen]):
        steam = Path("/usr/bin/steam")
        _patch_steam_path(mocker, steam)

        launch(via_steam=True, app_id=440, wait_timeout=0)

        assert fake_popen.last_argv == [str(steam), "-applaunch", "440"]

    def test_passes_no_vr_to_argv(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        _patch_steam_path(mocker, Path("/usr/bin/steam"))

        launch(via_steam=True, no_vr=True, wait_timeout=0)

        assert fake_popen.last_argv is not None
        assert "--no-vr" in fake_popen.last_argv

    def test_passes_osc_to_argv(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        _patch_steam_path(mocker, Path("/usr/bin/steam"))

        launch(via_steam=True, osc=OscConfig(in_port=9000), wait_timeout=0)

        assert fake_popen.last_argv is not None
        assert "--osc=9000:127.0.0.1:9001" in fake_popen.last_argv

    def test_raises_already_running_when_pre_pids_present(
        self, mocker: MockerFixture, fake_popen: type[FakePopen]
    ):
        del fake_popen
        _patch_steam_path(mocker, Path("/usr/bin/steam"))
        _process_iter_returning(
            mocker, FakeProcess(name=VRCHAT_PROCESS_NAME, pid=4242, create_time=1.0)
        )

        with pytest.raises(VRChatAlreadyRunningError, match="refocus"):
            launch(via_steam=True, wait_timeout=0)


class TestLaunchDirectSpawnWindows:
    """Windows direct-spawn path uses ``launch.exe`` with no umu wrapper."""

    def test_uses_launcher_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        fake_popen: type[FakePopen],
        tmp_path: Path,
    ):
        monkeypatch.setattr(sys, "platform", "win32")
        launcher = tmp_path / "launch.exe"
        launcher.write_bytes(b"")
        _patch_launcher(mocker, launcher)

        launch(wait_timeout=0)

        assert fake_popen.last_argv == [str(launcher)]

    def test_appends_vrchat_args(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        fake_popen: type[FakePopen],
        tmp_path: Path,
    ):
        monkeypatch.setattr(sys, "platform", "win32")
        launcher = tmp_path / "launch.exe"
        launcher.write_bytes(b"")
        _patch_launcher(mocker, launcher)

        launch(no_vr=True, screen_width=1280, wait_timeout=0)

        assert fake_popen.last_argv == [
            str(launcher),
            "--no-vr",
            "-screen-width",
            "1280",
        ]

    def test_uses_new_process_group(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        fake_popen: type[FakePopen],
        tmp_path: Path,
    ):
        monkeypatch.setattr(sys, "platform", "win32")
        launcher = tmp_path / "launch.exe"
        launcher.write_bytes(b"")
        _patch_launcher(mocker, launcher)

        launch(wait_timeout=0)

        assert "creationflags" in fake_popen.last_kwargs
        assert "start_new_session" not in fake_popen.last_kwargs

    def test_profile_forwards_to_argv(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        fake_popen: type[FakePopen],
        tmp_path: Path,
    ):
        # On Windows, profile only affects argv — no WINEPREFIX side effect.
        monkeypatch.setattr(sys, "platform", "win32")
        launcher = tmp_path / "launch.exe"
        launcher.write_bytes(b"")
        _patch_launcher(mocker, launcher)

        launch(profile=2, wait_timeout=0)

        assert fake_popen.last_argv == [str(launcher), "--profile=2"]
        env = fake_popen.last_kwargs.get("env")
        # No WINEPREFIX path on Windows.
        if env is not None:
            assert "WINEPREFIX" not in env


class TestLaunchDirectSpawnLinux:
    """Linux direct-spawn path wraps ``launch.exe`` with ``umu-run``."""

    def test_uses_umu_run(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
    ):
        launcher, umu = linux_direct_spawn

        launch(wait_timeout=0)

        assert fake_popen.last_argv == [str(umu), str(launcher)]

    def test_appends_vrchat_args(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
    ):
        launcher, umu = linux_direct_spawn

        launch(no_vr=True, wait_timeout=0)

        assert fake_popen.last_argv == [str(umu), str(launcher), "--no-vr"]

    @pytest.mark.parametrize("app_id", [VRCHAT_STEAM_APP_ID, 440])
    def test_does_not_set_gameid_env(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
        app_id: int,
    ):
        # GAMEID=438100 を umu-run に渡すと ProtonFixes が VRChat 用 fix を
        # 持たないために "global defaults" を当て、UMU-Proton-latest では未実装の
        # coremessaging.dll.DllGetActivationFactory を呼んで wine が即死する
        # (2026-05-23 実機観測)。app_id を変えても direct-spawn では env に
        # 乗らない (via_steam=True の steam.exe -applaunch <app_id> 経路でのみ
        # 意味を持つ)。
        del linux_direct_spawn

        launch(app_id=app_id, wait_timeout=0)

        env = fake_popen.last_kwargs.get("env")
        # env_overrides が空なら popen_env=None になり、Popen は親環境を継承する
        if env is not None:
            assert "GAMEID" not in env

    def test_sets_wineprefix_when_provided(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
        tmp_path: Path,
    ):
        del linux_direct_spawn
        prefix = tmp_path / "prefix"

        launch(wineprefix=prefix, wait_timeout=0)

        env = fake_popen.last_kwargs.get("env")
        assert isinstance(env, dict)
        assert env["WINEPREFIX"] == str(prefix)

    def test_creates_profile_wineprefix(
        self,
        monkeypatch: pytest.MonkeyPatch,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
        tmp_path: Path,
    ):
        del linux_direct_spawn
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        launch(profile=3, wait_timeout=0)

        expected_prefix = tmp_path / "vrcpilot" / "profiles" / "3" / "wineprefix"
        env = fake_popen.last_kwargs.get("env")
        assert isinstance(env, dict)
        assert env["WINEPREFIX"] == str(expected_prefix)
        # Side effect: directory was created so umu-run can use it.
        assert expected_prefix.is_dir()

    def test_profile_forwards_to_argv_and_sets_wineprefix(
        self,
        monkeypatch: pytest.MonkeyPatch,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
        tmp_path: Path,
    ):
        # Linux profile: both argv (--profile=N) and WINEPREFIX must be set.
        launcher, umu = linux_direct_spawn
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        launch(profile=2, wait_timeout=0)

        assert fake_popen.last_argv == [
            str(umu),
            str(launcher),
            "--profile=2",
        ]
        env = fake_popen.last_kwargs.get("env")
        assert isinstance(env, dict)
        assert "WINEPREFIX" in env

    def test_wineprefix_overrides_profile(
        self,
        monkeypatch: pytest.MonkeyPatch,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
        tmp_path: Path,
    ):
        del linux_direct_spawn
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        prefix = tmp_path / "explicit"

        launch(wineprefix=prefix, profile=4, wait_timeout=0)

        env = fake_popen.last_kwargs.get("env")
        assert isinstance(env, dict)
        assert env["WINEPREFIX"] == str(prefix)
        # And the auto-profile dir is NOT consulted.
        auto = tmp_path / "vrcpilot" / "profiles" / "4" / "wineprefix"
        assert not auto.exists()

    def test_sets_proton_path_when_provided(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
        tmp_path: Path,
    ):
        del linux_direct_spawn
        proton = tmp_path / "proton"

        launch(proton_path=proton, wait_timeout=0)

        env = fake_popen.last_kwargs.get("env")
        assert isinstance(env, dict)
        assert env["PROTON_PATH"] == str(proton)

    def test_uses_new_session(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
    ):
        del linux_direct_spawn

        launch(wait_timeout=0)

        assert fake_popen.last_kwargs.get("start_new_session") is True
        assert "creationflags" not in fake_popen.last_kwargs


class TestLaunchWait:
    """Post-spawn PID detection via pre/post ``find_pids()`` diff."""

    def test_wait_timeout_zero_returns_none(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
    ):
        del linux_direct_spawn, fake_popen

        assert launch(wait_timeout=0) is None

    def test_negative_wait_timeout_returns_none(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
    ):
        del linux_direct_spawn, fake_popen

        assert launch(wait_timeout=-1.0) is None

    def test_returns_new_pid_after_spawn(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
        mocker: MockerFixture,
    ):
        del linux_direct_spawn, fake_popen
        # Pre-spawn snapshot: nothing running. Post-spawn poll: PID 4242
        # alive — the diff identifies it as the new one.
        pre: list[FakeProcess] = []
        post = [FakeProcess(name=VRCHAT_PROCESS_NAME, pid=4242, create_time=10.0)]
        iters = iter([pre, post, post, post])
        mocker.patch(
            "vrcpilot.process.psutil.process_iter",
            side_effect=lambda *_a, **_kw: list(next(iters)),
        )

        result = launch(wait_timeout=5.0, wait_interval=0.01)

        assert result == 4242

    def test_returns_only_new_pid_diff_when_pre_existing_pids(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
        mocker: MockerFixture,
    ):
        """Pre-existing VRChat PIDs must be excluded from the new-PID
        result."""
        del linux_direct_spawn, fake_popen
        # First call (pre snapshot): one existing PID 100.
        # Second call (post-spawn poll loop): existing + brand-new PID 200.
        pre = [FakeProcess(name=VRCHAT_PROCESS_NAME, pid=100, create_time=1.0)]
        post = [
            FakeProcess(name=VRCHAT_PROCESS_NAME, pid=100, create_time=1.0),
            FakeProcess(name=VRCHAT_PROCESS_NAME, pid=200, create_time=2.0),
        ]
        # First invocation of process_iter returns the "pre" list, every
        # subsequent invocation returns the "post" list.
        iters = iter([pre, post, post, post])
        mocker.patch(
            "vrcpilot.process.psutil.process_iter",
            side_effect=lambda *_a, **_kw: list(next(iters)),
        )

        result = launch(wait_timeout=5.0, wait_interval=0.01)

        assert result == 200

    def test_returns_none_when_no_new_pid_appears(
        self,
        linux_direct_spawn: tuple[Path, Path],
        fake_popen: type[FakePopen],
    ):
        del linux_direct_spawn, fake_popen
        # autouse fixture: process_iter is empty -> no PID ever appears.
        result = launch(wait_timeout=0.05, wait_interval=0.01)

        assert result is None
