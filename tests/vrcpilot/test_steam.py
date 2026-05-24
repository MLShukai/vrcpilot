"""Tests for :mod:`vrcpilot.steam`.

Coverage split between two strategies:

* ``find_steam_executable`` is exercised with **real** filesystem and
  PATH manipulation -- no mocks. The override path uses tmp files; the
  Linux auto-detect path uses ``monkeypatch.setenv("PATH", ...)`` so
  ``shutil.which`` performs a real lookup against a fixture file.
* ``is_steam_running`` is **e2e-only**: it consults
  ``psutil.process_iter`` for an exact-named ``steam`` process, and the
  new test policy forbids patching that 3rd-party seam. We assert only
  the type contract (``bool``) here; the truth-value semantics belong
  in ``tests/e2e/``.

Public exception ``SteamNotRunningError`` carries no behaviour beyond
``RuntimeError``; no tests are written for that subclass relationship
(pyright + Python language already guarantee it).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import only_linux
from vrcpilot.steam import (
    SteamNotFoundError,
    find_steam_executable,
    is_steam_running,
)


class TestFindSteamExecutableOverride:
    """``override`` is platform-agnostic, so these tests run everywhere."""

    def test_returns_override_when_path_is_a_file(self, tmp_path: Path):
        fake_steam = tmp_path / "Steam.exe"
        fake_steam.write_bytes(b"")

        assert find_steam_executable(override=fake_steam) == fake_steam

    def test_raises_when_override_does_not_exist(self, tmp_path: Path):
        missing = tmp_path / "nope" / "Steam.exe"

        with pytest.raises(SteamNotFoundError, match="does not exist"):
            find_steam_executable(override=missing)

    def test_raises_when_override_is_a_directory(self, tmp_path: Path):
        # The gate is ``is_file()``: a directory must be rejected even
        # though the path resolves. Catches a regression where the check
        # falls back to ``Path.exists()`` and lets directories through.
        with pytest.raises(SteamNotFoundError, match="does not exist"):
            find_steam_executable(override=tmp_path)


class TestFindSteamExecutableLinuxAutoDetect:
    """Linux auto-detect path resolves ``steam`` via ``shutil.which``."""

    @only_linux
    def test_returns_path_when_steam_on_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        # Build a real fixture executable in tmp_path and set PATH to
        # exactly that directory. shutil.which performs a real PATH
        # lookup and discovers it -- no mocks of shutil itself.
        # A bare ``setenv("PATH", str(tmp_path))`` would shadow the
        # host's real ``steam`` install (if any), which is what we want.
        steam = tmp_path / "steam"
        steam.write_bytes(b"")
        steam.chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path))

        assert find_steam_executable() == steam

    @only_linux
    def test_raises_when_steam_not_on_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        # Empty PATH guarantees ``shutil.which`` returns None: tmp_path
        # contains no ``steam`` binary.
        monkeypatch.setenv("PATH", str(tmp_path))

        with pytest.raises(SteamNotFoundError, match="'steam' command not found"):
            find_steam_executable()


class TestIsSteamRunning:
    """``is_steam_running()`` is e2e-only territory.

    Asserting a specific truth value would require either:

    * a real ``steam`` desktop client on the runner (CI does not have
      one), or
    * a fake on ``vrcpilot.steam.psutil.process_iter`` (forbidden by the
      new policy -- ``psutil`` is a 3rd-party surface).

    The smoke check below verifies only the **type contract**: callers
    receive a ``bool``. Behaviour is covered by e2e scenarios that
    deliberately start / kill Steam.
    """

    def test_returns_bool(self):
        # No assumption about the value. The autouse ``_no_real_vrchat``
        # only patches the pid module's psutil; ``vrcpilot.steam`` reads
        # its own psutil, so the answer here reflects the actual host.
        assert isinstance(is_steam_running(), bool)
