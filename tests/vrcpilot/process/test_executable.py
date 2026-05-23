"""Tests for ``vrcpilot.process.executable``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vrcpilot.process import VRChatLauncherNotFoundError
from vrcpilot.process.executable import (
    find_vrchat_launcher,
    linux_steam_paths,
    parse_steam_library_paths,
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
        result = parse_steam_library_paths(vdf)
        assert len(result) == 2

    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        assert parse_steam_library_paths(tmp_path / "nope.vdf") == []


class TestSteamPathsHelpersReturnRootsOnly:
    """The platform helpers must enumerate Steam install **roots** only.

    Library expansion via ``libraryfolders.vdf`` is centralised in
    :func:`find_vrchat_launcher`; the helpers must not perform that
    expansion themselves, otherwise the responsibility for Steam library
    discovery would live in two places at once.
    """

    def test_linux_helper_does_not_expand_vdf(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Make ``~/.steam/steam`` resolve under tmp_path and plant a vdf
        # that references a library OUTSIDE the returned set. If the helper
        # were to expand the vdf, that library path would leak into the
        # returned list.
        monkeypatch.setenv("HOME", str(tmp_path))
        steam_root = tmp_path / ".steam" / "steam"
        vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        vdf.parent.mkdir(parents=True)
        library = tmp_path / "external-library"
        vdf.write_text(
            f'"libraryfolders" {{ "0" {{ "path" "{library.as_posix()}" }} }}',
            encoding="utf-8",
        )

        result = linux_steam_paths()

        # Roots only — no external library leak from vdf expansion.
        assert library not in result
        # And the canonical roots are exactly what the helper returns.
        assert result == [
            Path("~/.steam/steam").expanduser(),
            Path("~/.local/share/Steam").expanduser(),
        ]


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
        monkeypatch.setattr("vrcpilot.process.executable.linux_steam_paths", lambda: [])
        monkeypatch.setattr(
            "vrcpilot.process.executable.windows_steam_paths", lambda: []
        )
        with pytest.raises(VRChatLauncherNotFoundError):
            find_vrchat_launcher()

    def test_finds_launcher_via_libraryfolders(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``find_vrchat_launcher`` itself expands ``libraryfolders.vdf``.

        Verifies the centralised expansion: the platform helper returns
        only the Steam *root*, and ``find_vrchat_launcher`` is the one that
        reads the root's vdf and probes each listed library for
        ``launch.exe``.
        """
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
                "vrcpilot.process.executable.linux_steam_paths",
                lambda: [steam_root],
            )
        else:
            monkeypatch.setattr(
                "vrcpilot.process.executable.windows_steam_paths",
                lambda: [steam_root],
            )
        monkeypatch.delenv("VRCHAT_LAUNCHER", raising=False)
        result = find_vrchat_launcher()
        assert result == launch_exe

    def test_falls_back_to_root_when_vdf_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without a vdf the Steam root itself is treated as a library.

        Some installs (fresh, hand-edited, or non-standard layouts) lack
        a ``libraryfolders.vdf``. In that case ``launch.exe`` is expected
        directly under the root's ``steamapps/common/VRChat/`` tree.
        """
        steam_root = tmp_path / "steam"
        launch_exe = steam_root / "steamapps" / "common" / "VRChat" / "launch.exe"
        launch_exe.parent.mkdir(parents=True)
        launch_exe.write_bytes(b"")
        # Deliberately do NOT create ``steamapps/libraryfolders.vdf``.

        if sys.platform == "linux":
            monkeypatch.setattr(
                "vrcpilot.process.executable.linux_steam_paths",
                lambda: [steam_root],
            )
        else:
            monkeypatch.setattr(
                "vrcpilot.process.executable.windows_steam_paths",
                lambda: [steam_root],
            )
        monkeypatch.delenv("VRCHAT_LAUNCHER", raising=False)
        result = find_vrchat_launcher()
        assert result == launch_exe

    def test_raises_with_candidates_when_nothing_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("VRCHAT_LAUNCHER", raising=False)
        monkeypatch.setattr("vrcpilot.process.executable.linux_steam_paths", lambda: [])
        monkeypatch.setattr(
            "vrcpilot.process.executable.windows_steam_paths", lambda: []
        )
        with pytest.raises(VRChatLauncherNotFoundError, match="Tried"):
            find_vrchat_launcher()
