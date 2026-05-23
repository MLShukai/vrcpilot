"""Tests for ``vrcpilot.process._executable``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vrcpilot.process import (
    UmuLauncherNotFoundError,
    VRChatLauncherNotFoundError,
)
from vrcpilot.process._executable import (
    _parse_steam_library_paths,
    find_umu_launcher,
    find_vrchat_launcher,
)

_DUMMY_VDF = """"libraryfolders"
{
    "0"
    {
        "path"      "C:\\\\Program Files (x86)\\\\Steam"
        "label"     ""
    }
    "1"
    {
        "path"      "D:\\\\SteamLibrary"
        "label"     ""
    }
}
"""


class TestParseSteamLibraryPaths:
    def test_extracts_paths_from_vdf(self, tmp_path: Path) -> None:
        vdf = tmp_path / "libraryfolders.vdf"
        vdf.write_text(_DUMMY_VDF, encoding="utf-8")
        result = _parse_steam_library_paths(vdf)
        assert len(result) == 2

    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        assert _parse_steam_library_paths(tmp_path / "nope.vdf") == []


class TestFindVrchatLauncher:
    def test_uses_override_when_given(self, tmp_path: Path) -> None:
        exe = tmp_path / "launch.exe"
        exe.write_bytes(b"")
        result = find_vrchat_launcher(exe)
        assert result == exe

    def test_raises_when_override_missing(self, tmp_path: Path) -> None:
        with pytest.raises(VRChatLauncherNotFoundError, match="override"):
            find_vrchat_launcher(tmp_path / "missing.exe")

    def test_reads_env_var_when_no_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = tmp_path / "launch.exe"
        exe.write_bytes(b"")
        monkeypatch.setenv("VRCHAT_LAUNCHER", str(exe))
        result = find_vrchat_launcher()
        assert result == exe

    def test_skips_missing_env_var_value_falls_back_to_discovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VRCHAT_LAUNCHER", str(tmp_path / "nope.exe"))
        monkeypatch.setattr(
            "vrcpilot.process._executable._linux_steam_paths", lambda: []
        )
        monkeypatch.setattr(
            "vrcpilot.process._executable._windows_steam_paths", lambda: []
        )
        with pytest.raises(VRChatLauncherNotFoundError):
            find_vrchat_launcher()

    def test_finds_launcher_via_libraryfolders(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        library = tmp_path / "lib"
        launch_exe = library / "steamapps" / "common" / "VRChat" / "launch.exe"
        launch_exe.parent.mkdir(parents=True)
        launch_exe.write_bytes(b"")

        steam_root = tmp_path / "steam"
        vdf_dir = steam_root / "steamapps"
        vdf_dir.mkdir(parents=True)
        vdf = vdf_dir / "libraryfolders.vdf"
        vdf.write_text(
            f'"libraryfolders" {{ "0" {{ "path" "{library.as_posix()}" }} }}',
            encoding="utf-8",
        )

        if sys.platform == "linux":
            monkeypatch.setattr(
                "vrcpilot.process._executable._linux_steam_paths",
                lambda: [steam_root],
            )
        else:
            monkeypatch.setattr(
                "vrcpilot.process._executable._windows_steam_paths",
                lambda: [steam_root],
            )
        monkeypatch.delenv("VRCHAT_LAUNCHER", raising=False)
        result = find_vrchat_launcher()
        assert result == launch_exe

    def test_raises_with_candidates_when_nothing_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("VRCHAT_LAUNCHER", raising=False)
        monkeypatch.setattr(
            "vrcpilot.process._executable._linux_steam_paths", lambda: []
        )
        monkeypatch.setattr(
            "vrcpilot.process._executable._windows_steam_paths", lambda: []
        )
        with pytest.raises(VRChatLauncherNotFoundError, match="Tried"):
            find_vrchat_launcher()


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
        monkeypatch.setattr(
            "vrcpilot.process._executable.shutil.which", lambda _: str(umu)
        )
        result = find_umu_launcher()
        assert result == umu

    def test_raises_when_not_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("vrcpilot.process._executable.shutil.which", lambda _: None)
        with pytest.raises(UmuLauncherNotFoundError, match="PATH"):
            find_umu_launcher()
