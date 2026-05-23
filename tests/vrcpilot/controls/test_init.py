"""Tests for :mod:`vrcpilot.controls` public surface.

The subpackage and the top-level package must expose the same core
symbols: ``ensure_target``, :class:`VRChatNotFocusedError`, and the
:class:`Key` enum. Wiring them in two places is what lets users write
either ``vrcpilot.ensure_target`` or ``from vrcpilot.controls import
ensure_target`` interchangeably; if either re-export drifts away from
the canonical implementation, tests in other modules that
``mocker.patch`` one of them would silently miss the other call site.

``VRChatNotRunningError`` is no longer re-exported under
``vrcpilot.controls`` -- it lives on :mod:`vrcpilot.process` (where the
condition is detected) and is only exposed at the top level.
"""

from __future__ import annotations

from enum import StrEnum

import vrcpilot
import vrcpilot.controls
import vrcpilot.process
from vrcpilot.controls import keyboard as keyboard_mod, mouse as mouse_mod


class TestSubpackageSurface:
    def test_exposes_ensure_target(self):
        assert callable(vrcpilot.controls.ensure_target)

    def test_exposes_not_focused_error(self):
        assert issubclass(vrcpilot.controls.VRChatNotFocusedError, RuntimeError)

    def test_does_not_reexport_not_running_error(self):
        # VRChatNotRunningError lives on vrcpilot.process now; the
        # controls subpackage must not re-export it.
        assert not hasattr(vrcpilot.controls, "VRChatNotRunningError")

    def test_exposes_key_enum(self):
        assert issubclass(vrcpilot.controls.Key, StrEnum)

    def test_exposes_input_submodules(self):
        # Submodules are accessible as attributes of the subpackage so
        # callers can write ``vrcpilot.controls.mouse.click()`` without
        # an explicit ``import vrcpilot.controls.mouse``.
        assert vrcpilot.controls.mouse is mouse_mod
        assert vrcpilot.controls.keyboard is keyboard_mod


class TestTopLevelReexport:
    def test_ensure_target_is_same_object(self):
        assert vrcpilot.ensure_target is vrcpilot.controls.ensure_target

    def test_not_focused_error_is_same_object(self):
        assert vrcpilot.VRChatNotFocusedError is vrcpilot.controls.VRChatNotFocusedError

    def test_not_running_error_is_process_error(self):
        # Top-level alias points to the canonical class on
        # vrcpilot.process, not a controls re-export.
        assert vrcpilot.VRChatNotRunningError is vrcpilot.process.VRChatNotRunningError

    def test_key_is_same_object(self):
        assert vrcpilot.Key is vrcpilot.controls.Key

    def test_input_submodules_are_same_objects(self):
        # ``vrcpilot.mouse`` / ``vrcpilot.keyboard`` are the same
        # module objects as the canonical ones under
        # ``vrcpilot.controls`` -- the top-level alias is a convenience
        # rebinding, not a copy.
        assert vrcpilot.mouse is mouse_mod
        assert vrcpilot.keyboard is keyboard_mod
