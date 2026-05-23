"""Tests for :mod:`vrcpilot.window.linux`.

The module under test raises ``ImportError`` on non-Linux platforms,
and the real connection paths require a reachable X server. Two
module-level skips up front gate the rest of the file: platform first,
then display reachability. Below the gate, backend helpers receive an
explicit ``pid=`` argument now that the public dispatch layer
(:mod:`vrcpilot.window`) resolves it via :func:`vrcpilot.process.resolve_pid`.
The shared ``except Xlib.error.XError`` contract (any X protocol
failure surfaces as ``False``) is exercised once via
:class:`tests.fakes.FakeXWindow` on the simpler ``unfocus_window``
path, avoiding both a fragile real-X11 setup and wholesale Xlib-module
mocks.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "linux":
    pytest.skip("Linux-only module", allow_module_level=True)

from tests.helpers import has_x11_display

if not has_x11_display():
    pytest.skip("X11 display unavailable", allow_module_level=True)

from pytest_mock import MockerFixture

from tests.fakes import (
    FakeXDisplay,
    FakeXWindow,
    fake_x11_display_cm,
    make_xerror_subclass,
)
from vrcpilot.window.linux import focus_window, is_window_foreground, unfocus_window


class TestFocusWindow:
    def test_returns_false_on_wayland_native(self, monkeypatch: pytest.MonkeyPatch):
        # Drive the native-Wayland branch by twiddling real env vars
        # (``is_wayland_native`` reads ``XDG_SESSION_TYPE`` and
        # ``DISPLAY``). The branch must warn and return ``False``.
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("DISPLAY", raising=False)

        with pytest.warns(RuntimeWarning, match="Wayland native"):
            assert focus_window(pid=4242) is False

    def test_returns_false_when_window_not_found(self, mocker: MockerFixture):
        # PID is supplied directly now; backend no longer consults
        # ``find_pid``. With the X11 window lookup short-circuited to
        # ``None`` the helper must report ``False`` without sending any
        # ClientMessage.
        mocker.patch(
            "vrcpilot.window.linux.x11_display",
            return_value=fake_x11_display_cm(FakeXDisplay()),
        )
        mocker.patch(
            "vrcpilot.window.linux.find_vrchat_window",
            return_value=None,
        )

        assert focus_window(pid=4242) is False


class TestUnfocusWindow:
    def test_returns_false_on_wayland_native(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("DISPLAY", raising=False)

        with pytest.warns(RuntimeWarning, match="Wayland native"):
            assert unfocus_window(pid=4242) is False

    def test_returns_false_when_window_not_found(self, mocker: MockerFixture):
        mocker.patch(
            "vrcpilot.window.linux.x11_display",
            return_value=fake_x11_display_cm(FakeXDisplay()),
        )
        mocker.patch(
            "vrcpilot.window.linux.find_vrchat_window",
            return_value=None,
        )

        assert unfocus_window(pid=4242) is False

    def test_returns_false_on_xerror(self, mocker: MockerFixture):
        # Inject XError on ``window.configure``: FakeXWindow with
        # ``raises`` set throws on the first recorded call, exercising
        # the ``except Xlib.error.XError`` branch shared by both
        # ``focus_window`` and ``unfocus_window``. ``x11_display`` is
        # replaced with a fake context manager yielding a benign
        # FakeXDisplay (the lookup is short-circuited by patching
        # ``find_vrchat_window``).
        xerror_cls = make_xerror_subclass()
        mocker.patch(
            "vrcpilot.window.linux.x11_display",
            return_value=fake_x11_display_cm(FakeXDisplay()),
        )
        mocker.patch(
            "vrcpilot.window.linux.find_vrchat_window",
            return_value=FakeXWindow(raises=xerror_cls()),
        )

        assert unfocus_window(pid=4242) is False


class TestIsWindowForeground:
    def test_returns_false_on_wayland_native(self, monkeypatch: pytest.MonkeyPatch):
        # Same Wayland-detection path as focus/unfocus: env-flip drives
        # the warning + False short-circuit.
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("DISPLAY", raising=False)

        with pytest.warns(RuntimeWarning, match="Wayland native"):
            assert is_window_foreground(pid=4242) is False

    def test_returns_false_when_window_not_found(self, mocker: MockerFixture):
        mocker.patch(
            "vrcpilot.window.linux.x11_display",
            return_value=fake_x11_display_cm(FakeXDisplay()),
        )
        mocker.patch(
            "vrcpilot.window.linux.find_vrchat_window",
            return_value=None,
        )

        assert is_window_foreground(pid=4242) is False

    def test_returns_false_on_xerror(self, mocker: MockerFixture):
        # When the root window's ``get_full_property`` raises XError on
        # the ``_NET_ACTIVE_WINDOW`` lookup, the helper must surface
        # ``False`` rather than propagate. The VRChat window itself is
        # short-circuited via ``find_vrchat_window``; only the root
        # property read needs to fail.
        xerror_cls = make_xerror_subclass()
        vrchat_window = FakeXWindow(wid=42)
        root_window = FakeXWindow(wid=1, raises=xerror_cls())
        display = FakeXDisplay(root=root_window)

        mocker.patch(
            "vrcpilot.window.linux.x11_display",
            return_value=fake_x11_display_cm(display),
        )
        mocker.patch(
            "vrcpilot.window.linux.find_vrchat_window",
            return_value=vrchat_window,
        )

        assert is_window_foreground(pid=4242) is False

    def test_returns_true_when_active_matches_vrchat(self, mocker: MockerFixture):
        # Drive the happy path: root advertises ``_NET_ACTIVE_WINDOW``
        # holding the VRChat window's id, and ``find_vrchat_window``
        # hands back the same wid — so the helper reports ``True``.
        vrchat_window = FakeXWindow(wid=42)
        root_window = FakeXWindow(
            wid=1,
            properties={"_NET_ACTIVE_WINDOW": [42]},
        )
        display = FakeXDisplay(root=root_window)

        mocker.patch(
            "vrcpilot.window.linux.x11_display",
            return_value=fake_x11_display_cm(display),
        )
        mocker.patch(
            "vrcpilot.window.linux.find_vrchat_window",
            return_value=vrchat_window,
        )

        assert is_window_foreground(pid=4242) is True

    def test_returns_false_when_active_is_other_window(self, mocker: MockerFixture):
        # Active window id differs from the VRChat window's id - the
        # helper reports ``False`` so callers know to call ``focus()``.
        vrchat_window = FakeXWindow(wid=42)
        root_window = FakeXWindow(
            wid=1,
            properties={"_NET_ACTIVE_WINDOW": [99]},
        )
        display = FakeXDisplay(root=root_window)

        mocker.patch(
            "vrcpilot.window.linux.x11_display",
            return_value=fake_x11_display_cm(display),
        )
        mocker.patch(
            "vrcpilot.window.linux.find_vrchat_window",
            return_value=vrchat_window,
        )

        assert is_window_foreground(pid=4242) is False

    def test_returns_false_when_active_property_missing(self, mocker: MockerFixture):
        # WM that doesn't advertise ``_NET_ACTIVE_WINDOW`` (or the atom
        # is absent on root) returns ``None`` for the property read.
        # Helper must treat that as "not foreground".
        vrchat_window = FakeXWindow(wid=42)
        root_window = FakeXWindow(wid=1, properties={})
        display = FakeXDisplay(root=root_window)

        mocker.patch(
            "vrcpilot.window.linux.x11_display",
            return_value=fake_x11_display_cm(display),
        )
        mocker.patch(
            "vrcpilot.window.linux.find_vrchat_window",
            return_value=vrchat_window,
        )

        assert is_window_foreground(pid=4242) is False
