"""Tests for :mod:`vrcpilot` package top-level."""

import importlib
import sys
import tomllib
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

import vrcpilot

PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestPackage:
    def test_version(self):
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
            pyproject = tomllib.load(f)

        assert vrcpilot.__version__ == pyproject["project"]["version"]

    @pytest.mark.parametrize(
        "name",
        [
            "AudioCallback",
            "Speaker",
            "SpeakerLoop",
        ],
    )
    def test_speaker_modality_re_exported_at_top_level(self, name: str):
        """Speaker modality symbols must be in :data:`vrcpilot.__all__`.

        Pins the public-API surface the speaker package exposes through
        the top-level namespace so a refactor cannot quietly drop a re-
        export.
        """
        assert hasattr(vrcpilot, name)
        assert name in vrcpilot.__all__

    @pytest.mark.parametrize("name", ["Mic", "MicDeviceNotFoundError"])
    def test_mic_modality_re_exported_at_top_level(self, name: str):
        """Mic modality symbols must be in :data:`vrcpilot.__all__`.

        Pins the public-API surface the mic package exposes through the
        top-level namespace so a refactor cannot quietly drop a re-
        export.
        """
        assert hasattr(vrcpilot, name)
        assert name in vrcpilot.__all__

    @pytest.mark.parametrize(
        "name",
        [
            "VRCHAT_PROCESS_NAME",
            "VRCHAT_STEAM_APP_ID",
            "build_launch_command",
            "build_vrchat_launch_args",
            "recognize",
        ],
    )
    def test_internal_symbols_not_exposed_at_top_level(self, name: str):
        """Internal helpers must stay out of the top-level public surface.

        These names are intentionally excluded from the top-level public
        surface so that ``vrcpilot.<name>`` does not advertise internal
        plumbing or stale aliases. Process helpers remain importable via
        ``vrcpilot.process.<name>``; ``recognize`` was renamed to
        ``ocr`` in 0.1.0a-series and the old name is gone for good.
        """
        assert not hasattr(vrcpilot, name)
        assert name not in vrcpilot.__all__


class TestPidApis:
    """New PID-resolution helpers must reach the top-level namespace.

    ``find_pids`` and ``resolve_pid`` are the migration target for the
    deprecated ``find_pid``; pinning them at ``vrcpilot.<name>`` keeps the
    public surface stable as ``find_pid`` is phased out.
    """

    @pytest.mark.parametrize("name", ["find_pids", "resolve_pid"])
    def test_exposed_at_top_level(self, name: str) -> None:
        assert hasattr(vrcpilot, name)
        assert name in vrcpilot.__all__

    def test_find_pid_still_exposed(self) -> None:
        """``find_pid`` remains public until 0.4.0 removes the deprecation."""
        assert hasattr(vrcpilot, "find_pid")
        assert "find_pid" in vrcpilot.__all__


class TestNewProcessExceptions:
    """Multi-instance / launcher-discovery exceptions must be re-exported.

    Locks the public-error surface so callers can do
    ``except vrcpilot.VRChatMultipleInstancesError`` without reaching
    into ``vrcpilot.process``.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "VRChatMultipleInstancesError",
            "VRChatLauncherNotFoundError",
            "VRChatAlreadyRunningError",
            "UmuLauncherNotFoundError",
        ],
    )
    def test_exposed_at_top_level(self, name: str) -> None:
        assert hasattr(vrcpilot, name)
        assert name in vrcpilot.__all__


class TestLauncherDiscovery:
    """Launcher discovery helpers must be reachable from the top-level."""

    @pytest.mark.parametrize(
        "name",
        ["find_vrchat_launcher", "find_umu_launcher"],
    )
    def test_exposed_at_top_level(self, name: str) -> None:
        assert hasattr(vrcpilot, name)
        assert name in vrcpilot.__all__


class TestOcrAttributeAndSubmoduleCoexist:
    """Pin the function-vs-submodule shadowing of ``vrcpilot.ocr``.

    ``vrcpilot.ocr`` (attribute) is the OCR helper function, while
    ``from vrcpilot.ocr import OCREngine`` (submodule import) still
    works because Python's import machinery resolves submodule imports
    through ``sys.modules`` rather than attribute lookup. Both must
    keep working for the public API to behave as documented.
    """

    def test_top_level_ocr_attribute_is_callable(self):
        assert callable(vrcpilot.ocr)

    def test_submodule_import_still_works(self):
        from vrcpilot.ocr import OCREngine

        assert OCREngine.__name__ == "OCREngine"

    def test_ocr_is_in_all(self):
        assert "ocr" in vrcpilot.__all__


class TestUnsupportedPlatformGate:
    """``import vrcpilot`` must reject non-Windows / non-Linux hosts.

    The guard sits at the very top of :mod:`vrcpilot.__init__`, before
    any submodule import, so any host besides ``win32`` / ``linux``
    fails fast with a clear diagnostic instead of hitting a missing
    backend import deeper in the package.

    Because ``vrcpilot`` is already imported by the time pytest reaches
    this test, the guard is retriggered with :func:`importlib.reload`
    inside a patched-``sys.platform`` context.
    """

    @pytest.mark.parametrize("platform", ["darwin", "freebsd", "openbsd"])
    def test_reimport_raises_on_unsupported_platform(
        self, mocker: MockerFixture, platform: str
    ) -> None:
        mocker.patch.object(sys, "platform", platform)
        with pytest.raises(ImportError, match="vrcpilot supports only"):
            importlib.reload(vrcpilot)

    def test_supported_platform_reimports_cleanly(self, mocker: MockerFixture) -> None:
        # Reloading without the patch (or with a supported platform) is
        # a no-op for the gate; this pins that the reload path itself
        # is healthy so a failing parametrized case above is attributable
        # to the gate and not to ``importlib.reload`` machinery.
        mocker.patch.object(sys, "platform", sys.platform)
        reloaded = importlib.reload(vrcpilot)
        assert reloaded is vrcpilot
