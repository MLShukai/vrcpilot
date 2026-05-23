"""Tests for :mod:`vrcpilot.steam`."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

from tests.helpers import only_linux
from vrcpilot.steam import (
    SteamNotFoundError,
    SteamNotRunningError,
    find_steam_executable,
    is_steam_running,
)


class TestFindSteamExecutableOverride:
    """``override`` is platform-agnostic — verify on the current host."""

    def test_override_returns_existing_path(self, tmp_path: Path):
        fake_steam = tmp_path / "Steam.exe"
        fake_steam.write_bytes(b"")

        result = find_steam_executable(override=fake_steam)

        assert result == fake_steam

    def test_override_missing_path_raises(self, tmp_path: Path):
        missing = tmp_path / "nope" / "Steam.exe"

        with pytest.raises(SteamNotFoundError, match="does not exist"):
            find_steam_executable(override=missing)

    def test_override_directory_raises(self, tmp_path: Path):
        # ``is_file()`` is the gate, so a directory should be rejected even
        # though the path exists.
        with pytest.raises(SteamNotFoundError, match="does not exist"):
            find_steam_executable(override=tmp_path)


class TestFindSteamExecutableLinux:
    """Linux auto-detect path delegates to ``shutil.which``."""

    @only_linux
    def test_returns_path_when_steam_on_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        steam = tmp_path / "steam"
        steam.write_bytes(b"")
        monkeypatch.setattr("vrcpilot.steam.shutil.which", lambda _name: str(steam))

        assert find_steam_executable() == steam

    @only_linux
    def test_raises_when_not_on_path(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("vrcpilot.steam.shutil.which", lambda _name: None)

        with pytest.raises(SteamNotFoundError, match="'steam' command not found"):
            find_steam_executable()


class TestIsSteamRunning:
    """:func:`is_steam_running` probes psutil for a ``steam`` process."""

    def test_returns_true_when_steam_in_process_list(self, mocker: MockerFixture):
        steam_proc = SimpleNamespace(info={"name": "steam"})
        mocker.patch("vrcpilot.steam.psutil.process_iter", return_value=[steam_proc])

        assert is_steam_running() is True

    def test_returns_false_when_steam_absent(self, mocker: MockerFixture):
        unrelated = SimpleNamespace(info={"name": "firefox"})
        mocker.patch("vrcpilot.steam.psutil.process_iter", return_value=[unrelated])

        assert is_steam_running() is False

    def test_does_not_match_steam_helper_processes(self, mocker: MockerFixture):
        # Exact-equality match: ``steamwebhelper`` / ``steam-runtime-...``
        # children should not satisfy the predicate.
        helper = SimpleNamespace(info={"name": "steamwebhelper"})
        runtime = SimpleNamespace(info={"name": "steam-runtime-launcher-service"})
        mocker.patch(
            "vrcpilot.steam.psutil.process_iter",
            return_value=[helper, runtime],
        )

        assert is_steam_running() is False

    def test_returns_false_on_empty_process_list(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.steam.psutil.process_iter", return_value=[])

        assert is_steam_running() is False


class TestSteamNotRunningError:
    """:class:`SteamNotRunningError` is a public exception subclass."""

    def test_inherits_from_runtime_error(self):
        assert issubclass(SteamNotRunningError, RuntimeError)

    def test_carries_message(self):
        err = SteamNotRunningError("Steam is not running")
        assert "Steam is not running" in str(err)
