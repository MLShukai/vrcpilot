"""Shared fixtures for the :mod:`vrcpilot.controls` test suite.

The :func:`fake_vrchat_window` fixture patches
``vrcpilot.controls.mouse.base.get_vrchat_window_rect`` to a fixed
rectangle so tests that exercise the window-local -> desktop
translation in :meth:`Mouse.move` get a deterministic origin without
needing a real VRChat process. Coordinates assume the window occupies
``(200, 100) - (1480, 820)`` (origin (200, 100), size 1280x720); test
expectations should be expressed relative to that origin.
"""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture


@pytest.fixture
def fake_vrchat_window(mocker: MockerFixture) -> tuple[int, int, int, int]:
    """Pin :func:`vrcpilot.geometry.get_vrchat_window_rect` to a fixed rect.

    Returns the patched ``(x, y, width, height)`` tuple so tests can
    derive expected desktop-absolute coordinates without hard-coding
    the magic numbers twice.
    """
    rect = (200, 100, 1280, 720)
    mocker.patch(
        "vrcpilot.controls.mouse.base.get_vrchat_window_rect",
        return_value=rect,
    )
    return rect
