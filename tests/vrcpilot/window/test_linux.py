"""Tests for :mod:`vrcpilot.window.linux` (X11/XWayland focus backend).

The module under test raises ``ImportError`` on non-Linux platforms,
and the focus paths require a reachable X server. Two module-level
skips up front gate the rest of the file: platform first, then
display reachability.

Backend helpers now accept an explicit ``pid=`` (the public dispatch
layer in :mod:`vrcpilot.window` resolves the PID). Tests pass either
an unused PID -- exercising the "window not found" branch against the
real X11 client-list walk -- or the live tkinter window's PID --
exercising the focus/is_foreground round-trip against the live X
server. No 3rd-party-Xlib surface mocking and no internal-function
mocking is used.

The Wayland-native branch is exercised purely by environment
variables (``XDG_SESSION_TYPE`` / ``DISPLAY``) because that is the
exact mechanism :func:`vrcpilot.session.is_wayland_native` consults --
no monkey-patching of vrcpilot internals is needed.
"""

from __future__ import annotations

import os
import sys

import pytest

if sys.platform != "linux":
    pytest.skip("vrcpilot.window.linux is Linux-only", allow_module_level=True)

from tests.helpers import has_x11_display

if not has_x11_display():
    pytest.skip("X11 display unavailable", allow_module_level=True)

import tkinter
from collections.abc import Iterator

from vrcpilot.window.linux import (
    focus_window,
    is_window_foreground,
    unfocus_window,
)

_UNUSED_PID = 99_999_999


@pytest.fixture
def tk_window() -> Iterator[tkinter.Tk]:
    """Spawn a real Tk top-level window mapped on the X display.

    ``update()`` forces the WM round-trip so the window appears in
    ``_NET_CLIENT_LIST`` with ``_NET_WM_PID == os.getpid()`` -- which
    is what the backend matches against. Destroyed on teardown so
    other tests do not see a stray window.
    """
    root = tkinter.Tk()
    root.geometry("320x240+50+60")
    root.update_idletasks()
    root.update()
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def wayland_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive ``is_wayland_native()`` to return True via real env vars.

    ``XDG_SESSION_TYPE=wayland`` AND no ``DISPLAY`` is the exact
    condition :func:`vrcpilot.session.is_wayland_native` reads, so the
    backend's Wayland-native short-circuit fires without any mocking.
    """
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.delenv("DISPLAY", raising=False)


class TestFocusWindow:
    def test_warns_and_returns_false_on_wayland_native(self, wayland_env: None):
        # Native Wayland is explicitly unsupported. Contract: emit
        # RuntimeWarning AND return False (so polling callers can keep
        # going rather than crash).
        _ = wayland_env

        with pytest.warns(RuntimeWarning, match="Wayland native"):
            assert focus_window(pid=_UNUSED_PID) is False

    def test_returns_false_when_no_window_owns_pid(self):
        # Real ``find_vrchat_window`` walk against the live X server;
        # no window owns ``_UNUSED_PID`` so the helper short-circuits
        # to False without sending any ClientMessage.
        assert focus_window(pid=_UNUSED_PID) is False

    def test_returns_true_for_existing_window(self, tk_window: tkinter.Tk):
        # Real focus round-trip: spawn a tk window, send the EWMH
        # ``_NET_ACTIVE_WINDOW`` ClientMessage to the WM. The WM may or
        # may not honour the request (depends on focus-stealing policy)
        # but the helper's contract is to return True once the message
        # was successfully sent and flushed -- which it will be on any
        # cooperating EWMH WM.
        _ = tk_window

        assert focus_window(pid=os.getpid()) is True


class TestIsWindowForeground:
    def test_warns_and_returns_false_on_wayland_native(self, wayland_env: None):
        _ = wayland_env

        with pytest.warns(RuntimeWarning, match="Wayland native"):
            assert is_window_foreground(pid=_UNUSED_PID) is False

    def test_returns_false_when_no_window_owns_pid(self):
        # Helper short-circuits before reading ``_NET_ACTIVE_WINDOW``
        # when no window matches the PID.
        assert is_window_foreground(pid=_UNUSED_PID) is False


class TestUnfocusWindow:
    def test_warns_and_returns_false_on_wayland_native(self, wayland_env: None):
        _ = wayland_env

        with pytest.warns(RuntimeWarning, match="Wayland native"):
            assert unfocus_window(pid=_UNUSED_PID) is False

    def test_returns_false_when_no_window_owns_pid(self):
        assert unfocus_window(pid=_UNUSED_PID) is False

    def test_returns_true_for_existing_window(self, tk_window: tkinter.Tk):
        # ``window.configure(stack_mode=X.Below)`` succeeds against the
        # live tk window: the X server accepts the configure request,
        # the helper flushes, and returns True. We do not assert the
        # resulting z-order because that depends on which other windows
        # happen to be open on the runner.
        _ = tk_window

        assert unfocus_window(pid=os.getpid()) is True
