"""Tests for :mod:`vrcpilot.window.windows`.

The module under test imports Windows-only DLLs (``pywintypes``,
``win32gui``, ``win32api``) and raises ``ImportError`` on any other
platform. A module-level skip up front keeps non-Windows runners from
even attempting the import — anything below executes only on Windows.

Backend helpers now receive an explicit ``pid=`` argument; the public
dispatch layer (:mod:`vrcpilot.window`) is responsible for resolving it
via :func:`vrcpilot.process.resolve_pid`. These tests therefore drive
backend functions directly with a PID and patch ``find_vrchat_hwnd`` /
Win32 APIs to exercise the remaining branches.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only module", allow_module_level=True)

import pywintypes
from pytest_mock import MockerFixture

from vrcpilot.window.windows import focus_window, is_window_foreground, unfocus_window


class TestFocusWindow:
    def test_returns_false_when_hwnd_not_found(self, mocker: MockerFixture):
        # PID is supplied directly now; backend no longer consults
        # ``find_pid``. With ``find_vrchat_hwnd`` returning ``None`` the
        # helper must report ``False`` without invoking any Win32 API.
        mocker.patch("vrcpilot.window.windows.find_vrchat_hwnd", return_value=None)

        assert focus_window(pid=4242) is False


class TestUnfocusWindow:
    def test_returns_false_when_hwnd_not_found(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.window.windows.find_vrchat_hwnd", return_value=None)

        assert unfocus_window(pid=4242) is False

    def test_returns_false_on_pywintypes_error(self, mocker: MockerFixture):
        # ``unfocus_window`` has the simplest call chain among the two
        # helpers (one Win32 call inside the ``try``); injecting
        # ``pywintypes.error`` here documents the shared contract that
        # any platform-level failure is converted to a ``False`` return
        # rather than propagated.
        mocker.patch("vrcpilot.window.windows.find_vrchat_hwnd", return_value=12345)
        mocker.patch(
            "vrcpilot.window.windows.win32gui.SetWindowPos",
            side_effect=pywintypes.error(0, "SetWindowPos", "msg"),
        )

        assert unfocus_window(pid=4242) is False


class TestIsWindowForeground:
    def test_returns_false_when_hwnd_not_found(self, mocker: MockerFixture):
        # VRChat process is running but the top-level HWND owned by it
        # could not be located (e.g. the window is not yet created).
        # The helper must report ``False`` without invoking
        # ``GetForegroundWindow``.
        mocker.patch("vrcpilot.window.windows.find_vrchat_hwnd", return_value=None)

        assert is_window_foreground(pid=4242) is False

    def test_returns_true_when_hwnd_matches_foreground(self, mocker: MockerFixture):
        # Happy path: the located HWND equals the OS-reported
        # foreground HWND, so the helper reports ``True``.
        mocker.patch("vrcpilot.window.windows.find_vrchat_hwnd", return_value=12345)
        mocker.patch(
            "vrcpilot.window.windows.win32gui.GetForegroundWindow",
            return_value=12345,
        )

        assert is_window_foreground(pid=4242) is True

    def test_returns_false_when_hwnd_does_not_match_foreground(
        self, mocker: MockerFixture
    ):
        # A different window owns the foreground - the helper reports
        # ``False`` so callers know to call ``focus()``.
        mocker.patch("vrcpilot.window.windows.find_vrchat_hwnd", return_value=12345)
        mocker.patch(
            "vrcpilot.window.windows.win32gui.GetForegroundWindow",
            return_value=99999,
        )

        assert is_window_foreground(pid=4242) is False

    def test_returns_false_on_pywintypes_error(self, mocker: MockerFixture):
        # Any pywintypes failure during the foreground check must be
        # converted to a ``False`` return rather than propagated, so
        # the helper plays the same defensive contract as
        # ``focus_window`` / ``unfocus_window``.
        mocker.patch("vrcpilot.window.windows.find_vrchat_hwnd", return_value=12345)
        mocker.patch(
            "vrcpilot.window.windows.win32gui.GetForegroundWindow",
            side_effect=pywintypes.error(0, "GetForegroundWindow", "msg"),
        )

        assert is_window_foreground(pid=4242) is False
