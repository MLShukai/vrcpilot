"""Tests for :mod:`vrcpilot` package top-level."""

import tomllib
from pathlib import Path

import pytest

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
