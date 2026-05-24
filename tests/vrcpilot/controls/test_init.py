"""Tests for :mod:`vrcpilot.controls` public surface.

The subpackage re-exports a small set of names that the user-facing
:mod:`vrcpilot` namespace aliases (``Key``, ``MouseButton``,
``VRChatNotFocusedError``, the ``keyboard`` / ``mouse`` submodules).
These are public-API contract pins (Hyrum's-law mitigation), not
behaviour tests: callers depend on the identity of those objects being
the same as the canonical ones under :mod:`vrcpilot.controls.*` so an
``isinstance`` check or ``except`` clause works regardless of which
import path was used.
"""

from __future__ import annotations

import pytest

import vrcpilot
import vrcpilot.controls
from vrcpilot.controls import keyboard as keyboard_mod, mouse as mouse_mod


@pytest.mark.api_contract
class TestControlsSubpackageReExports:
    """Contract pin: top-level aliases must point at the canonical objects.

    Users write ``except vrcpilot.VRChatNotFocusedError`` /
    ``vrcpilot.Key.A`` / ``vrcpilot.mouse.click()`` and expect those to
    refer to the same class / enum / module they could reach via the
    longer ``vrcpilot.controls.*`` path. Identity (``is``) -- not
    equality -- is the load-bearing property.
    """

    def test_not_focused_error_is_same_object(self) -> None:
        assert vrcpilot.VRChatNotFocusedError is vrcpilot.controls.VRChatNotFocusedError

    def test_key_enum_is_same_object(self) -> None:
        assert vrcpilot.Key is vrcpilot.controls.Key

    def test_mouse_button_enum_is_same_object(self) -> None:
        assert vrcpilot.MouseButton is vrcpilot.controls.MouseButton

    def test_keyboard_submodule_is_same_object(self) -> None:
        # ``vrcpilot.keyboard`` is a rebinding of the canonical submodule
        # under ``vrcpilot.controls.keyboard``, not a copy. Module
        # identity matters because ``vrcpilot.keyboard.press`` and
        # ``vrcpilot.controls.keyboard.press`` must mutate the same
        # lazy-singleton ``_instance``.
        assert vrcpilot.keyboard is keyboard_mod
        assert vrcpilot.controls.keyboard is keyboard_mod

    def test_mouse_submodule_is_same_object(self) -> None:
        assert vrcpilot.mouse is mouse_mod
        assert vrcpilot.controls.mouse is mouse_mod
