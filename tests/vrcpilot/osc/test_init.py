"""Tests for :mod:`vrcpilot.osc` package surface."""

from __future__ import annotations

import vrcpilot
import vrcpilot.osc as osc_pkg


class TestOscPackageAll:
    def test_all_contents(self) -> None:
        assert set(osc_pkg.__all__) == {
            "AvatarParameters",
            "InputController",
            "OscSender",
            "SupportsBool",
        }

    def test_each_name_resolves(self) -> None:
        for name in osc_pkg.__all__:
            assert hasattr(osc_pkg, name)


class TestTopLevelExposure:
    def test_top_level_exports_osc_classes(self) -> None:
        assert vrcpilot.OscSender is osc_pkg.OscSender
        assert vrcpilot.InputController is osc_pkg.InputController
        assert vrcpilot.AvatarParameters is osc_pkg.AvatarParameters

    def test_classes_listed_in_top_level_all(self) -> None:
        for name in ("OscSender", "InputController", "AvatarParameters"):
            assert name in vrcpilot.__all__
