"""Published API contract for the ``vrcpilot`` top-level package.

Every test in this file is an **API contract pin**, not a behaviour
test. The published surface (``__version__``, ``__all__``,
function/submodule shadowing) is what downstream users import and what
breakage stories like "we silently leaked an internal helper" depend
on. These pins exist so any unintended drift in the top-level surface
shows up as a failing test rather than a Hyrum's-law surprise.

Behavioural tests for individual symbols live next to the modules they
come from (e.g. ``tests/vrcpilot/process/`` for ``find_pid``).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import vrcpilot

pytestmark = pytest.mark.api_contract

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestVersion:
    """``vrcpilot.__version__`` is the distribution metadata version.

    Project policy: the single source of truth is
    ``pyproject.toml [project].version``; the runtime attribute is
    resolved via ``importlib.metadata``. Hard-coding the version in
    code would create a second source of truth that silently drifts.
    """

    def test_runtime_version_matches_pyproject(self) -> None:
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as fp:
            pyproject = tomllib.load(fp)
        declared = pyproject["project"]["version"]

        assert vrcpilot.__version__ == declared


# The exact published top-level surface. Listed verbatim here (not
# derived from ``vrcpilot.__all__``) so an unintended addition or
# removal in the package shows up as a contract diff in this file.
#
# Anything **outside** this set must NOT be in ``vrcpilot.__all__`` and
# must NOT be reachable as ``vrcpilot.<name>`` — internal helpers stay
# on their subpackages so ``dir(vrcpilot)`` advertises only the
# user-facing entry points.
EXPECTED_PUBLIC_SURFACE: frozenset[str] = frozenset(
    {
        "__version__",
        "CaptureLoop",
        "clipboard",
        "detect",
        "find_pid",
        "find_pids",
        "focus",
        "is_foreground",
        "Key",
        "keyboard",
        "launch",
        "Mic",
        "MicDeviceNotFoundError",
        "mouse",
        "MouseButton",
        "ocr",
        "OscConfig",
        "OscSender",
        "Screenshot",
        "SteamNotFoundError",
        "take_screenshot",
        "terminate",
        "unfocus",
        "VRChatMultipleInstancesError",
        "VRChatNotFocusedError",
        "VRChatNotRunningError",
    }
)


class TestPublicSurface:
    """``vrcpilot.__all__`` is the contract for the top-level namespace.

    A name in ``__all__`` is a promise that ``from vrcpilot import
    <name>`` will keep working. A name absent from ``__all__`` is a
    promise that callers should not depend on it being top-level (it
    may move under a subpackage at any time).
    """

    def test_all_matches_expected_surface(self) -> None:
        # ``__all__`` is the wildcard-import contract. Pinning the
        # exact set forces a code review here for any addition or
        # removal — addition usually means "did we mean to publish
        # this?" and removal means "this is a breaking change".
        assert set(vrcpilot.__all__) == EXPECTED_PUBLIC_SURFACE

    @pytest.mark.parametrize("name", sorted(EXPECTED_PUBLIC_SURFACE))
    def test_every_public_name_is_attribute_accessible(self, name: str) -> None:
        # ``__all__`` only controls ``from vrcpilot import *``; this
        # pins that every advertised name also resolves via
        # ``vrcpilot.<name>`` attribute access (i.e. it was actually
        # imported into the namespace, not merely listed).
        assert hasattr(vrcpilot, name)

    # Names that have appeared either as internal helpers or as former
    # public symbols. Pinning their *absence* documents the boundary so
    # a stray re-export shows up here.
    @pytest.mark.parametrize(
        "name",
        [
            # Subsystem implementation classes — live on subpackages.
            "Capture",
            "OCREngine",
            "OCRResult",
            "OCRWord",
            "RapidOCREngine",
            "DetectEngine",
            "DetectResult",
            "Detection",
            "TemplateDetectEngine",
            "InputController",
            "AvatarParameters",
            "Speaker",
            "SpeakerLoop",
            "AudioCallback",
            "ensure_target",
            # Launch / process internals — accessed via vrcpilot.process.
            "VRCHAT_PROCESS_NAME",
            "VRCHAT_STEAM_APP_ID",
            "build_launch_command",
            "build_vrchat_launch_args",
            "find_vrchat_launcher",
            "find_umu_launcher",
            "resolve_pid",
            # Launcher-discovery / environment-validation exceptions —
            # too narrow for top-level; callers catch the broader
            # ``VRChatNotRunningError`` / ``VRChatMultipleInstancesError``.
            "VRChatLauncherNotFoundError",
            "VRChatAlreadyRunningError",
            "VRChatDisplayNotAvailableError",
            "UmuLauncherNotFoundError",
            "SteamNotRunningError",
            # Renamed in the 0.1.0a series; the old name must stay gone.
            "recognize",
        ],
    )
    def test_internal_or_legacy_name_is_not_top_level(self, name: str) -> None:
        assert name not in vrcpilot.__all__
        assert not hasattr(vrcpilot, name)


class TestOcrFunctionAndSubmoduleCoexist:
    """``vrcpilot.ocr`` is *both* a callable and an importable submodule.

    ``vrcpilot.__init__`` imports the function ``ocr`` from
    ``vrcpilot.ocr``, which shadows the submodule attribute on the
    package object. Python's import machinery still resolves
    ``from vrcpilot.ocr import OCREngine`` via ``sys.modules`` rather
    than attribute lookup, so both shapes have to keep working in
    parallel for the documented API.
    """

    def test_top_level_ocr_is_callable(self) -> None:
        assert callable(vrcpilot.ocr)

    def test_submodule_import_still_resolves(self) -> None:
        # If the shadowing ever broke the submodule resolution, this
        # import would raise ``ImportError`` at collection time.
        from vrcpilot.ocr import OCREngine

        assert OCREngine.__name__ == "OCREngine"


class TestProcessExceptionInheritance:
    """Top-level VRChat process exceptions inherit from ``Exception``.

    Pinning the inheritance chain is a Hyrum's-law mitigation: users
    write ``except vrcpilot.VRChatNotRunningError`` and we must not
    silently re-base these classes onto something narrower (e.g.
    ``OSError``) or wider (``BaseException``) without thinking.
    """

    @pytest.mark.parametrize(
        "exc",
        [
            vrcpilot.VRChatNotRunningError,
            vrcpilot.VRChatMultipleInstancesError,
            vrcpilot.VRChatNotFocusedError,
            vrcpilot.MicDeviceNotFoundError,
            vrcpilot.SteamNotFoundError,
        ],
    )
    def test_exception_inherits_from_exception(self, exc: type[BaseException]) -> None:
        # ``Exception`` (not ``BaseException``) so callers' bare
        # ``except Exception:`` catches these without also swallowing
        # ``KeyboardInterrupt`` / ``SystemExit``.
        assert issubclass(exc, Exception)
