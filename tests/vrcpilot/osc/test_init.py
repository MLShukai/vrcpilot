"""Tests for :mod:`vrcpilot.osc` package surface."""

from __future__ import annotations

import vrcpilot
import vrcpilot.osc as osc_pkg


class TestOscPackageAll:
    def test_all_contents(self):
        assert set(osc_pkg.__all__) == {
            "AvatarParameters",
            "InputController",
            "OscSender",
        }

    def test_each_name_resolves(self):
        for name in osc_pkg.__all__:
            assert hasattr(osc_pkg, name)


class TestTopLevelExposure:
    """Only ``OscSender`` (the low-level transport) is re-exported.

    ``InputController`` and ``AvatarParameters`` are higher-level
    composers built on top of ``OscSender`` and remain accessible via
    :mod:`vrcpilot.osc` to keep the top-level namespace narrow.
    """

    def test_top_level_exports_osc_sender(self):
        assert vrcpilot.OscSender is osc_pkg.OscSender

    def test_osc_sender_listed_in_top_level_all(self):
        assert "OscSender" in vrcpilot.__all__

    def test_input_controller_not_top_level(self):
        assert not hasattr(vrcpilot, "InputController")
        assert "InputController" not in vrcpilot.__all__

    def test_avatar_parameters_not_top_level(self):
        assert not hasattr(vrcpilot, "AvatarParameters")
        assert "AvatarParameters" not in vrcpilot.__all__
