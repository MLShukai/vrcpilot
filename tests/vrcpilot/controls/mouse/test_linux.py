"""Tests for :mod:`vrcpilot.controls.mouse.linux`.

Linux-only and requires both ``/dev/uinput`` write access (for
``inputtino.Mouse``) and a reachable X11 display (for ``mss.MSS`` to
read the desktop bounding box at construction time). Three module-level
skips gate the rest of the file:

1. Non-Linux platforms (the module raises :class:`ImportError`).
2. ``/dev/uinput`` not writable (inputtino opens the device at
   constructor time; see ``tests/e2e/mouse.py`` for the udev setup).
3. No X11 display reachable (``mss`` cannot probe the desktop bounds
   without one).

The tests cover only the pure-logic parts of the backend:

* The ``_BUTTON_MAP`` translation table (every public
  :class:`MouseButton` value has an inputtino target).
* Constructor smoke: ``/dev/uinput`` opens and mss reports positive
  screen bounds.

Mouse button / cursor / scroll dispatch is intentionally **not**
exercised at unit level: a real ``mouseDown`` would click on
whichever window happens to be under the developer's cursor, and a
real ``scroll_vertical`` would scroll whichever window is focused.
The 120-per-notch scroll-unit conversion in ``_do_scroll`` is
verified at e2e where the side effect lands inside a VRChat window
that owns the cursor.
"""

from __future__ import annotations

import os
import sys

import pytest

if sys.platform != "linux":
    pytest.skip(
        "vrcpilot.controls.mouse.linux is Linux-only",
        allow_module_level=True,
    )

if not os.access("/dev/uinput", os.W_OK):
    pytest.skip(
        "/dev/uinput is not writable; see tests/e2e/mouse.py for setup",
        allow_module_level=True,
    )

from tests.helpers import has_x11_display  # noqa: E402

if not has_x11_display():
    pytest.skip(
        "X11 display required for mss-based screen probe",
        allow_module_level=True,
    )

import inputtino  # noqa: E402

from vrcpilot.controls.mouse.base import MouseButton  # noqa: E402
from vrcpilot.controls.mouse.linux import _BUTTON_MAP, LinuxMouse  # noqa: E402


class TestButtonMapCoverage:
    """Every public :class:`MouseButton` must map to an inputtino target.

    A missing entry would surface as :class:`KeyError` at the first
    ``_do_press`` / ``_do_release`` call. Pulling that failure
    forward to test-discovery time matches the keyboard backend's
    ``_INPUTTINO_CODES`` exhaustiveness check.
    """

    def test_every_button_maps_to_an_inputtino_button(self) -> None:
        assert set(_BUTTON_MAP.keys()) == set(MouseButton)

    def test_every_mapped_value_is_an_inputtino_button(self) -> None:
        for member, target in _BUTTON_MAP.items():
            assert isinstance(
                target, inputtino.MouseButton
            ), f"{member!r} maps to non-MouseButton value {target!r}"

    @pytest.mark.parametrize(
        "button,target_name",
        [
            (MouseButton.LEFT, "LEFT"),
            (MouseButton.RIGHT, "RIGHT"),
            (MouseButton.MIDDLE, "MIDDLE"),
        ],
    )
    def test_known_name_translations(
        self, button: MouseButton, target_name: str
    ) -> None:
        assert _BUTTON_MAP[button] is getattr(inputtino.MouseButton, target_name)


class TestLinuxMouseConstructs:
    """Construction opens ``/dev/uinput`` and reads the screen bounds.

    A failure here is either a uinput / X11 deployment issue or a real
    spec regression. The positive-bounds assertion confirms the mss
    probe found a display (rather than silently returning zeros).
    """

    def test_construct_populates_positive_screen_dimensions(self) -> None:
        m = LinuxMouse()
        assert m._screen_w > 0
        assert m._screen_h > 0


# ``_do_scroll(n)`` calls inputtino with ``n * 120`` units (inputtino's
# scroll API takes high-resolution wheel units, not plain notches). The
# conversion is verified at e2e (``tests/e2e/mouse.py``) where the
# side effect lands inside the VRChat window that owns the cursor.
# Driving it at unit level would scroll the developer's desktop session.
