"""Tests for :mod:`vrcpilot.process.linux`.

This module is Linux-only at the source level: ``import
vrcpilot.process.linux`` raises ``ImportError`` on Windows. The skip
must therefore be a module-level skip placed *before* any import of
the SUT.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.platform != "linux":
    pytest.skip("vrcpilot.process.linux is Linux-only", allow_module_level=True)

from vrcpilot.process import (  # noqa: E402  -- after module-level skip
    UmuLauncherNotFoundError,
    VRChatDisplayNotAvailableError,
)
from vrcpilot.process.linux import (  # noqa: E402
    find_umu_launcher,
    preflight_linux_environment,
    profile_wineprefix,
    steam_compatdata_pfx,
)


class TestFindUmuLauncherOverride:
    def test_returns_override_when_path_is_a_file(self, tmp_path: Path):
        umu = tmp_path / "umu-run"
        umu.write_bytes(b"")

        assert find_umu_launcher(umu) == umu

    def test_raises_when_override_missing(self, tmp_path: Path):
        with pytest.raises(UmuLauncherNotFoundError, match="override"):
            find_umu_launcher(tmp_path / "missing")


class TestFindUmuLauncherAutoDetect:
    """Auto-detect uses ``shutil.which`` against the real ``PATH``."""

    def test_finds_umu_run_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Build a real fixture under tmp_path and constrain PATH to
        # exactly that directory. ``shutil.which`` performs the real
        # PATH lookup -- no mocks of shutil itself.
        umu = tmp_path / "umu-run"
        umu.write_bytes(b"")
        umu.chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path))

        assert find_umu_launcher() == umu

    def test_raises_when_umu_not_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Empty PATH guarantees no ``umu-run`` discovery. Message must
        # mention PATH so the user knows where to install it.
        monkeypatch.setenv("PATH", str(tmp_path))

        with pytest.raises(UmuLauncherNotFoundError, match="PATH"):
            find_umu_launcher()


class TestPreflightLinuxEnvironmentDirectSpawn:
    """``via_steam=False``: requires a graphical display (X11 or Wayland)."""

    def test_raises_when_neither_display_nor_wayland_display_set(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        with pytest.raises(VRChatDisplayNotAvailableError, match="DISPLAY"):
            preflight_linux_environment(via_steam=False)

    def test_accepts_x11_display_alone(self, monkeypatch: pytest.MonkeyPatch):
        # X11 (or XWayland) -- DISPLAY satisfies the check.
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        preflight_linux_environment(via_steam=False)

    def test_accepts_wayland_display_alone(self, monkeypatch: pytest.MonkeyPatch):
        # Wayland-native -- WAYLAND_DISPLAY alone is enough.
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

        preflight_linux_environment(via_steam=False)

    def test_rejects_empty_display_string(self, monkeypatch: pytest.MonkeyPatch):
        # ``DISPLAY=""`` is what a stripped systemd unit env produces.
        # It must be treated as "unset" so the check is not satisfied
        # by an empty string.
        monkeypatch.setenv("DISPLAY", "")
        monkeypatch.setenv("WAYLAND_DISPLAY", "")

        with pytest.raises(VRChatDisplayNotAvailableError):
            preflight_linux_environment(via_steam=False)


# NOTE: ``preflight_linux_environment(via_steam=True)`` calls
# ``vrcpilot.steam.is_steam_running()`` which reads the live psutil
# process table. The new test policy forbids patching the
# ``psutil.process_iter`` 3rd-party seam, so the via_steam paths are
# covered by tests/e2e/ (where a real ``steam`` desktop client is the
# fixture).


class TestProfileWineprefix:
    """Profile path derives from ``$XDG_DATA_HOME`` (with ``HOME``
    fallback)."""

    def test_uses_xdg_data_home_when_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        result = profile_wineprefix(2)

        assert result == tmp_path / "vrcpilot" / "profiles" / "2" / "wineprefix"

    def test_falls_back_to_dot_local_share_under_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        # No XDG_DATA_HOME -> ``$HOME/.local/share`` is the default per
        # the XDG Base Directory spec.
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        result = profile_wineprefix(5)

        assert result == (
            tmp_path / ".local" / "share" / "vrcpilot" / "profiles" / "5" / "wineprefix"
        )

    def test_zero_is_a_valid_profile_number(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        # 0 is a legal profile (default VRChat profile). The path
        # generator must not special-case it as "missing".
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        result = profile_wineprefix(0)

        assert result == tmp_path / "vrcpilot" / "profiles" / "0" / "wineprefix"


class TestSteamCompatdataPfx:
    """``steam_compatdata_pfx`` derives the Steam-managed Proton prefix path
    from a VRChat ``launch.exe`` location.

    Spec: ``profile=0`` on Linux opts into sharing the wineprefix that
    Steam already manages for VRChat (so login state and SaveData line
    up with a ``--via-steam`` run). The path layout that Steam uses is
    ``<library>/steamapps/compatdata/<app_id>/pfx``, with the same
    ``<library>`` root that hosts ``steamapps/common/VRChat/launch.exe``.
    This helper is the pure path-derivation step of that lookup; the
    existence check (and the resulting
    :class:`VRChatSteamCompatdataNotFoundError`) happens at the call
    site inside :func:`vrcpilot.process.launch`.
    """

    def test_derives_pfx_under_same_library_as_launcher(self, tmp_path: Path):
        # The launcher lives at the canonical Steam-library layout
        # ``<library>/steamapps/common/VRChat/launch.exe``. The Proton
        # prefix Steam maintains for the same app sits sibling under
        # ``<library>/steamapps/compatdata/<app_id>/pfx``. Both legs
        # share the same ``<library>`` root, which is what makes
        # profile=0 (= "reuse Steam's prefix") work without the user
        # spelling the prefix out.
        library = tmp_path / "SteamLibrary"
        launcher = library / "steamapps" / "common" / "VRChat" / "launch.exe"

        result = steam_compatdata_pfx(launcher, 438100)

        assert result == library / "steamapps" / "compatdata" / "438100" / "pfx"

    def test_app_id_is_stringified_in_path(self, tmp_path: Path):
        # ``<app_id>`` becomes a path component, so it must render as
        # the decimal string ``"438100"`` rather than e.g. ``b'438100'``
        # or a Path-coerced form.
        library = tmp_path / "SteamLibrary"
        launcher = library / "steamapps" / "common" / "VRChat" / "launch.exe"

        result = steam_compatdata_pfx(launcher, 12345)

        assert result.parent.name == "12345"
        assert result.name == "pfx"

    def test_does_not_check_existence(self, tmp_path: Path):
        # Pure path-derivation: passing a launcher path that does not
        # exist must NOT raise. The existence gate (and the resulting
        # ``VRChatSteamCompatdataNotFoundError``) belongs at the
        # ``launch()`` call site, not here -- tests at that layer want
        # to drive both "prefix present" and "prefix missing" branches
        # without having to fabricate a launcher first.
        missing_launcher = (
            tmp_path / "nonexistent" / "steamapps" / "common" / "VRChat" / "launch.exe"
        )
        assert not missing_launcher.exists()

        result = steam_compatdata_pfx(missing_launcher, 438100)

        assert result == (
            tmp_path / "nonexistent" / "steamapps" / "compatdata" / "438100" / "pfx"
        )
        # The returned path is also non-existent: the function does not
        # create it, so a caller can probe ``is_dir()`` to decide
        # whether to fail fast.
        assert not result.exists()
