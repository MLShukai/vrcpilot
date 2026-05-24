"""Tests for :mod:`vrcpilot.process.executable`.

All tests use real filesystem fixtures under ``tmp_path``; the
discovery chain (VDF parsing, ``Path.is_file`` probing) runs unchanged.
On Linux, ``HOME`` is repointed at ``tmp_path`` so the canonical Steam
roots (``~/.steam/steam`` etc.) resolve under our controlled tree --
no monkeypatching of vrcpilot's own discovery helpers required.

On Windows the auto-detect path consults the registry via ``winreg``;
those branches are e2e-only here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import only_linux
from vrcpilot.process import VRChatLauncherNotFoundError
from vrcpilot.process.executable import (
    find_vrchat_launcher,
    parse_steam_library_paths,
    steam_paths,
)

_VDF_WITH_TWO_LIBRARIES = """"libraryfolders"
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


def _make_launcher(library_root: Path) -> Path:
    """Lay out ``<library>/steamapps/common/VRChat/launch.exe`` under tmp."""
    launch_exe = library_root / "steamapps" / "common" / "VRChat" / "launch.exe"
    launch_exe.parent.mkdir(parents=True)
    launch_exe.write_bytes(b"")
    return launch_exe


class TestParseSteamLibraryPaths:
    def test_extracts_every_path_entry(self, tmp_path: Path):
        vdf = tmp_path / "libraryfolders.vdf"
        vdf.write_text(_VDF_WITH_TWO_LIBRARIES, encoding="utf-8")

        result = parse_steam_library_paths(vdf)

        assert len(result) == 2

    def test_returns_empty_list_when_file_missing(self, tmp_path: Path):
        # ``read_text`` raises ``OSError`` for a missing file. The
        # helper must absorb that and return ``[]`` so callers can
        # treat "no vdf" the same as "no libraries listed".
        assert parse_steam_library_paths(tmp_path / "nope.vdf") == []


class TestSteamPathsReturnsRootsOnly:
    """``steam_paths`` enumerates *install roots*, not libraries.

    Library expansion via ``libraryfolders.vdf`` is centralised in
    :func:`find_vrchat_launcher`. If this helper expanded the vdf
    itself, library discovery would live in two places and drift.
    """

    @only_linux
    def test_returns_canonical_roots_unchanged_by_vdf_presence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Plant a vdf under the canonical root pointing at an OUTSIDE
        # library. If the helper were to expand the vdf, that library
        # path would leak into the result.
        monkeypatch.setenv("HOME", str(tmp_path))
        steam_root = tmp_path / ".steam" / "steam"
        vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        vdf.parent.mkdir(parents=True)
        external = tmp_path / "external-library"
        vdf.write_text(
            f'"libraryfolders" {{ "0" {{ "path" "{external.as_posix()}" }} }}',
            encoding="utf-8",
        )

        result = steam_paths()

        assert external not in result
        assert result == [
            Path("~/.steam/steam").expanduser(),
            Path("~/.local/share/Steam").expanduser(),
        ]


class TestFindVrchatLauncherOverride:
    """Override path is platform-agnostic; runs everywhere."""

    def test_returns_override_when_path_is_a_file(self, tmp_path: Path):
        exe = tmp_path / "launch.exe"
        exe.write_bytes(b"")

        assert find_vrchat_launcher(exe) == exe

    def test_raises_when_override_does_not_exist(self, tmp_path: Path):
        with pytest.raises(VRChatLauncherNotFoundError, match="override"):
            find_vrchat_launcher(tmp_path / "missing.exe")


class TestFindVrchatLauncherEnvVar:
    """``VRCHAT_LAUNCHER`` env var resolution; platform-agnostic."""

    def test_reads_env_var_when_no_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        exe = tmp_path / "launch.exe"
        exe.write_bytes(b"")
        monkeypatch.setenv("VRCHAT_LAUNCHER", str(exe))

        assert find_vrchat_launcher() == exe


class TestFindVrchatLauncherDiscoveryLinux:
    """Linux discovery chain driven by real ``HOME`` manipulation.

    Both canonical roots (``~/.steam/steam`` and ``~/.local/share/Steam``)
    resolve under ``tmp_path`` so the real ``steam_paths()`` /
    ``find_vrchat_launcher`` chain runs end-to-end against fixtures we
    control -- no monkeypatching of vrcpilot's own helpers required.
    """

    @only_linux
    def test_expands_libraryfolders_vdf_and_finds_launcher(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Set up HOME so ``~/.steam/steam`` resolves under tmp_path.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("VRCHAT_LAUNCHER", raising=False)

        # Plant the launcher under a separate "library" dir, then point
        # the canonical root's vdf at that library. find_vrchat_launcher
        # must read the vdf at the root and probe each listed library.
        library = tmp_path / "lib"
        launch_exe = _make_launcher(library)

        steam_root = tmp_path / ".steam" / "steam"
        vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        vdf.parent.mkdir(parents=True)
        vdf.write_text(
            f'"libraryfolders" {{ "0" {{ "path" "{library.as_posix()}" }} }}',
            encoding="utf-8",
        )

        assert find_vrchat_launcher() == launch_exe

    @only_linux
    def test_falls_back_to_root_when_vdf_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Some installs (fresh / hand-edited / non-standard) lack a
        # vdf. The launcher is then expected directly under the root's
        # ``steamapps/common/VRChat/`` tree.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("VRCHAT_LAUNCHER", raising=False)

        steam_root = tmp_path / ".steam" / "steam"
        launch_exe = _make_launcher(steam_root)
        # Deliberately do NOT create ``steamapps/libraryfolders.vdf``.

        assert find_vrchat_launcher() == launch_exe

    @only_linux
    def test_falls_back_to_dot_local_share_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Second canonical root: ``~/.local/share/Steam``. Plant the
        # launcher only there and verify the discovery still finds it.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("VRCHAT_LAUNCHER", raising=False)

        steam_root = tmp_path / ".local" / "share" / "Steam"
        launch_exe = _make_launcher(steam_root)

        assert find_vrchat_launcher() == launch_exe


class TestFindVrchatLauncherNotFound:
    """Discovery exhausted without finding the launcher."""

    @only_linux
    def test_error_message_lists_candidates_tried_on_linux(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Empty HOME with no launcher anywhere: discovery must fail and
        # the message must include a "Tried" section so the user knows
        # which candidate paths to override.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("VRCHAT_LAUNCHER", raising=False)

        with pytest.raises(VRChatLauncherNotFoundError, match="Tried"):
            find_vrchat_launcher()

    @only_linux
    def test_env_var_pointing_at_missing_file_does_not_short_circuit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # The env var path is best-effort: a missing target must fall
        # through to library discovery, not abort. Pin HOME at an empty
        # tmp_path so the real ``steam_paths()`` returns roots
        # that exist on disk but contain no launcher -- the discovery
        # chain reaches the NotFound error without any internal helper
        # being monkeypatched. Windows' registry-based auto-detect has
        # no HOME-style operation and is covered by e2e instead.
        monkeypatch.setenv("HOME", str(tmp_path))
        missing = tmp_path / "nope.exe"
        monkeypatch.setenv("VRCHAT_LAUNCHER", str(missing))

        with pytest.raises(VRChatLauncherNotFoundError) as excinfo:
            find_vrchat_launcher()

        # "fall-through happened" の証拠を pin する: env var の path も
        # discovery 候補も "Tried" に列挙されること。env var で abort
        # していたら discovery 候補は現れない。
        msg = str(excinfo.value)
        assert str(missing) in msg
        assert ".steam/steam" in msg
