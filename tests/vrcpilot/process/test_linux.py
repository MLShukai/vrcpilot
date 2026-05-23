"""Tests for :mod:`vrcpilot.process.linux`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="vrcpilot.process.linux is Linux-only"
)

from vrcpilot.process import UmuLauncherNotFoundError  # noqa: E402
from vrcpilot.process.linux import find_umu_launcher  # noqa: E402


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
