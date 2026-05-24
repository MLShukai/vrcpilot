"""Package-surface contract pins for :mod:`vrcpilot.osc`.

These are *contract pins* (Hyrum's-law mitigation), not behavioural
tests. External users do ``from vrcpilot.osc import OscSender`` and
``from vrcpilot import OscSender``; the names that resolve from each
import path are part of the public API and changing them must be a
deliberate, visible diff. See SKILL.md section "公開 API 契約ピン".
"""

from __future__ import annotations

import vrcpilot
import vrcpilot.osc as osc_pkg


class TestPackageAll:
    """Contract: ``vrcpilot.osc.__all__`` enumerates the package surface."""

    def test_all_lists_the_three_exposed_names(self):
        # Contract pin: external imports rely on these exact names.
        assert set(osc_pkg.__all__) == {
            "AvatarParameters",
            "InputController",
            "OscSender",
        }


class TestTopLevelReExport:
    """Contract: only the low-level transport ``OscSender`` is re-exported.

    The high-level composers (:class:`InputController`,
    :class:`AvatarParameters`) live under :mod:`vrcpilot.osc` to keep
    the top-level namespace narrow. Promoting them is a deliberate
    decision, not an accident.
    """

    def test_osc_sender_is_re_exported_as_same_object(self):
        # Contract pin: ``vrcpilot.OscSender`` and ``vrcpilot.osc.OscSender``
        # must be the same class so users can mix import paths safely.
        assert vrcpilot.OscSender is osc_pkg.OscSender

    def test_osc_sender_listed_in_top_level_all(self):
        # Contract pin: ``OscSender`` is part of the top-level public API.
        assert "OscSender" in vrcpilot.__all__

    def test_input_controller_not_promoted_to_top_level(self):
        # Contract pin: deliberately scoped to ``vrcpilot.osc``.
        assert "InputController" not in vrcpilot.__all__

    def test_avatar_parameters_not_promoted_to_top_level(self):
        # Contract pin: deliberately scoped to ``vrcpilot.osc``.
        assert "AvatarParameters" not in vrcpilot.__all__
