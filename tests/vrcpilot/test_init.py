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
    def test_speaker_modality_not_exposed_at_top_level(self, name: str):
        """Speaker backend classes stay on :mod:`vrcpilot.speaker`.

        The top-level namespace is reserved for user-facing entry
        points; ``Speaker`` / ``SpeakerLoop`` / ``AudioCallback`` are
        backend / loop implementations and live on the subpackage
        (``vrcpilot.speaker.Speaker`` etc.) -- leaking them at top level
        would obscure that boundary.
        """
        assert not hasattr(vrcpilot, name)
        assert name not in vrcpilot.__all__

    @pytest.mark.parametrize("name", ["Mic", "MicDeviceNotFoundError"])
    def test_mic_modality_re_exported_at_top_level(self, name: str):
        """Mic modality symbols must be in :data:`vrcpilot.__all__`.

        ``Mic`` is the user-facing capture API and its companion error
        is the one callers catch; both stay top-level so users can
        write ``vrcpilot.Mic(...)`` /
        ``except vrcpilot.MicDeviceNotFoundError`` without reaching
        into the subpackage.
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

    @pytest.mark.parametrize(
        "name",
        [
            # Capture backend class (loop driver ``CaptureLoop`` stays
            # top-level for the user-facing record API).
            "Capture",
            # OCR engine / data classes (``ocr`` function stays top-level).
            "OCREngine",
            "OCRResult",
            "OCRWord",
            "RapidOCREngine",
            # Detect engine / data classes (``detect`` function stays
            # top-level).
            "DetectEngine",
            "DetectResult",
            "Detection",
            "TemplateDetectEngine",
            # OSC high-level helpers (``OscSender`` low-level stays
            # top-level).
            "InputController",
            "AvatarParameters",
            # Controls helper accessed indirectly via keyboard / mouse
            # focus guard.
            "ensure_target",
        ],
    )
    def test_subsystem_implementation_classes_not_exposed_at_top_level(self, name: str):
        """Subsystem implementation surfaces live on their subpackages.

        Engines, ABCs, data classes, and helper-facing controllers are
        accessed through their subpackages
        (``vrcpilot.capture.Capture``, ``vrcpilot.ocr.OCREngine``,
        ``vrcpilot.detect.Detection``, ``vrcpilot.osc.InputController``,
        ``vrcpilot.controls.ensure_target``). The top-level namespace is
        reserved for user-facing entry points so a quick
        ``dir(vrcpilot)`` highlights what callers should reach for.
        """
        assert not hasattr(vrcpilot, name)
        assert name not in vrcpilot.__all__


class TestPidApis:
    """PID-resolution helpers' top-level surface.

    ``find_pids`` is the migration target for the deprecated
    ``find_pid``; pinning it at ``vrcpilot.find_pids`` keeps the public
    surface stable as ``find_pid`` is phased out. ``resolve_pid`` is the
    internal "0 / 1 / N -> pid" disambiguator used by CLI subcommands
    and stays scoped to :mod:`vrcpilot.process`.
    """

    def test_find_pids_exposed_at_top_level(self) -> None:
        assert hasattr(vrcpilot, "find_pids")
        assert "find_pids" in vrcpilot.__all__

    def test_find_pid_still_exposed(self) -> None:
        """``find_pid`` remains public until 0.4.0 removes the deprecation."""
        assert hasattr(vrcpilot, "find_pid")
        assert "find_pid" in vrcpilot.__all__

    def test_resolve_pid_not_at_top_level(self) -> None:
        """``resolve_pid`` is internal -- accessed via
        :mod:`vrcpilot.process`."""
        assert not hasattr(vrcpilot, "resolve_pid")
        assert "resolve_pid" not in vrcpilot.__all__


class TestProcessExceptionsTopLevel:
    """The catchable user-facing process errors must be re-exported.

    These are the exceptions callers actually need at runtime -- VRChat
    being multi-instance or not running blocks most APIs. Pinning them
    at ``vrcpilot.<name>`` lets code write
    ``except vrcpilot.VRChatMultipleInstancesError`` without reaching
    into :mod:`vrcpilot.process`.
    """

    @pytest.mark.parametrize(
        "name",
        ["VRChatMultipleInstancesError", "VRChatNotRunningError"],
    )
    def test_exposed_at_top_level(self, name: str) -> None:
        assert hasattr(vrcpilot, name)
        assert name in vrcpilot.__all__


class TestProcessExceptionsNotTopLevel:
    """Launcher-discovery / environment-validation errors stay subpackage-
    local.

    These exceptions surface only from ``launch()`` set-up paths
    (missing launcher binary, VRChat already running on this profile,
    no DISPLAY on Linux) and the typical caller does not need to catch
    them separately from the multi-instance / not-running cases. They
    remain importable via ``vrcpilot.process.<name>`` /
    ``vrcpilot.steam.<name>``.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "VRChatLauncherNotFoundError",
            "VRChatAlreadyRunningError",
            "VRChatDisplayNotAvailableError",
            "UmuLauncherNotFoundError",
            "SteamNotRunningError",
        ],
    )
    def test_not_exposed_at_top_level(self, name: str) -> None:
        assert not hasattr(vrcpilot, name)
        assert name not in vrcpilot.__all__


class TestLauncherDiscoveryNotTopLevel:
    """Launcher discovery helpers are intentionally **not** top-level.

    They live in :mod:`vrcpilot.process.executable` (cross-platform
    ``find_vrchat_launcher``) and :mod:`vrcpilot.process.linux`
    (``find_umu_launcher``). The top-level namespace is reserved for
    user-facing APIs; ``launch()`` is the entry point that internally
    consults the launcher helpers.
    """

    @pytest.mark.parametrize(
        "name",
        ["find_vrchat_launcher", "find_umu_launcher"],
    )
    def test_not_exposed_at_top_level(self, name: str) -> None:
        assert not hasattr(vrcpilot, name)
        assert name not in vrcpilot.__all__


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
