"""Tests for :mod:`vrcpilot.process.linux`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.platform != "linux":
    pytest.skip("vrcpilot.process.linux is Linux-only", allow_module_level=True)

from vrcpilot.process import (
    UmuLauncherNotFoundError,
    VRChatDisplayNotAvailableError,
)
from vrcpilot.process.linux import (
    find_umu_launcher,
    preflight_linux_environment,
    profile_wineprefix,
)
from vrcpilot.steam import SteamNotRunningError


class TestFindUmuLauncher:
    def test_uses_override_when_given(self, tmp_path: Path) -> None:
        umu = tmp_path / "umu-run"
        umu.write_bytes(b"")
        result = find_umu_launcher(umu)
        assert result == umu

    def test_raises_when_override_missing(self, tmp_path: Path) -> None:
        with pytest.raises(UmuLauncherNotFoundError, match="override"):
            find_umu_launcher(tmp_path / "missing")

    def test_uses_shutil_which_when_no_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        umu = tmp_path / "umu-run"
        umu.write_bytes(b"")
        monkeypatch.setattr("vrcpilot.process.linux.shutil.which", lambda _: str(umu))
        result = find_umu_launcher()
        assert result == umu

    def test_raises_when_not_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("vrcpilot.process.linux.shutil.which", lambda _: None)
        with pytest.raises(UmuLauncherNotFoundError, match="PATH"):
            find_umu_launcher()


class TestPreflightLinuxEnvironment:
    """Linux runtime preflight (DISPLAY for direct-spawn, Steam for
    via_steam)."""

    def test_direct_spawn_raises_without_display(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        with pytest.raises(VRChatDisplayNotAvailableError, match="DISPLAY"):
            preflight_linux_environment(via_steam=False)

    def test_direct_spawn_accepts_x11_display(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        preflight_linux_environment(via_steam=False)

    def test_direct_spawn_accepts_wayland_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

        preflight_linux_environment(via_steam=False)

    def test_direct_spawn_rejects_empty_display(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An empty string should be treated the same as "unset" so the
        # check is not satisfied by ``DISPLAY=`` left over from a stripped
        # systemd unit env.
        monkeypatch.setenv("DISPLAY", "")
        monkeypatch.setenv("WAYLAND_DISPLAY", "")

        with pytest.raises(VRChatDisplayNotAvailableError):
            preflight_linux_environment(via_steam=False)

    def test_via_steam_raises_when_steam_not_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("vrcpilot.steam.is_steam_running", lambda: False)
        # No DISPLAY required for via_steam — verify the check skips it
        # entirely.
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        with pytest.raises(SteamNotRunningError, match="Steam"):
            preflight_linux_environment(via_steam=True)

    def test_via_steam_passes_when_steam_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("vrcpilot.steam.is_steam_running", lambda: True)
        # DISPLAY-less environment must not fail the via_steam path: Steam
        # owns the display attachment in that case.
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        preflight_linux_environment(via_steam=True)


class TestProfileWineprefix:
    def test_uses_xdg_data_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        result = profile_wineprefix(2)

        assert result == tmp_path / "vrcpilot" / "profiles" / "2" / "wineprefix"

    def test_falls_back_to_dot_local_share(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        result = profile_wineprefix(5)

        assert (
            result
            == tmp_path
            / ".local"
            / "share"
            / "vrcpilot"
            / "profiles"
            / "5"
            / "wineprefix"
        )

    def test_zero_profile_path_shape(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        result = profile_wineprefix(0)

        assert result.name == "wineprefix"
        assert result.parent.name == "0"
