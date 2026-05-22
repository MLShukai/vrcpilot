"""Tests for :mod:`vrcpilot.win32`.

The module under test imports Windows-only DLLs (``pywintypes``,
``win32gui``, ``win32process``) and raises ``ImportError`` on any
other platform. A module-level skip up front keeps non-Windows runners
from even attempting the import — anything below executes only on
Windows.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only module", allow_module_level=True)

from pytest_mock import MockerFixture

from vrcpilot.win32 import find_vrchat_hwnd, get_window_rect


class TestFindVrchatHwnd:
    """Real ``EnumWindows`` walk; no real VRChat process running.

    Passing a sentinel PID that no real process owns is enough to
    exercise the enumeration without depending on any specific window
    being open. The helper must report ``None`` rather than raise.
    """

    def test_returns_none_for_unknown_pid(self):
        # ``-1`` is never a valid Windows PID; with no matching window
        # the helper must surface ``None``.
        assert find_vrchat_hwnd(-1) is None


class TestGetWindowRect:
    def test_returns_none_for_invalid_hwnd(self):
        # ``0`` is not a valid HWND. ``GetWindowRect`` raises
        # ``pywintypes.error`` for it; the helper must convert that to
        # ``None`` and not propagate.
        assert get_window_rect(0) is None

    def test_returns_none_when_rect_query_raises(self, mocker: MockerFixture):
        # When the underlying API raises ``pywintypes.error`` (HWND
        # destroyed mid-call) the helper must surface ``None`` rather
        # than propagate. Patching the API is the only way to drive
        # this branch deterministically without owning a real HWND
        # that disappears on cue.
        import pywintypes

        mocker.patch(
            "vrcpilot.win32.win32gui.GetWindowRect",
            side_effect=pywintypes.error(
                1400, "GetWindowRect", "Invalid window handle."
            ),
        )

        assert get_window_rect(99999) is None

    @pytest.mark.parametrize(
        ("rect"),
        [
            (100, 200, 100, 800),  # zero width
            (100, 200, 900, 200),  # zero height
            (100, 200, 50, 800),  # negative width (right < left)
            (100, 200, 900, 100),  # negative height (bottom < top)
        ],
    )
    def test_returns_none_on_degenerate_rect(
        self,
        mocker: MockerFixture,
        rect: tuple[int, int, int, int],
    ):
        # Degenerate rectangles cannot occur for a real visible HWND but
        # are cheap to drive via a patch and document the boundary
        # contract (``width <= 0 or height <= 0`` -> ``None``).
        mocker.patch("vrcpilot.win32.win32gui.GetWindowRect", return_value=rect)

        assert get_window_rect(12345) is None
