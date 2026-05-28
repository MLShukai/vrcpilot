"""Tests for :mod:`vrcpilot.window.linux` (X11/XWayland focus backend).

The module under test raises ``ImportError`` on non-Linux platforms,
and the focus paths require a reachable X server. Two module-level
skips up front gate the rest of the file: platform first, then
display reachability.

Backend helpers now accept an explicit ``pid=`` (the public dispatch
layer in :mod:`vrcpilot.window` resolves the PID). Tests pass either
an unused PID -- exercising the "window not found" branch against the
real X11 client-list walk -- or the live spawned window's PID --
exercising the focus/is_foreground round-trip against the live X
server. No 3rd-party-Xlib surface mocking and no internal-function
mocking is used.

The "existing window" tests spawn a real top-level X11 window via raw
Xlib calls (rather than ``tkinter``). EWMH-compliant WMs such as
Mutter only insert toolkit-decorated top-levels into
``_NET_CLIENT_LIST`` after a reparent dance that does not propagate
``_NET_WM_PID`` onto the frame, so a tk window with the correct PID
on its content sub-window is invisible to the production walk. A bare
``InputOutput`` window we open ourselves goes straight into
``_NET_CLIENT_LIST`` with ``_NET_WM_PID`` intact -- which is exactly
what VRChat's main window looks like to the WM at runtime.

The Wayland-native branch is exercised purely by environment
variables (``XDG_SESSION_TYPE`` / ``DISPLAY``) because that is the
exact mechanism :func:`vrcpilot.session.is_wayland_native` consults --
no monkey-patching of vrcpilot internals is needed.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator

import pytest

if sys.platform != "linux":
    pytest.skip("vrcpilot.window.linux is Linux-only", allow_module_level=True)

from tests.helpers import has_x11_display

if not has_x11_display():
    pytest.skip("X11 display unavailable", allow_module_level=True)

import Xlib.display
from Xlib import X, Xatom
from Xlib.xobject.drawable import Window as _XWindow

from vrcpilot.linux import open_x11_display
from vrcpilot.window.linux import (
    focus_window,
    is_window_foreground,
    unfocus_window,
)

_UNUSED_PID = 99_999_999

# Upper bound for waiting on the WM to insert a freshly-mapped window
# into ``_NET_CLIENT_LIST``. Two seconds comfortably covers the
# Mutter / GNOME-Shell round-trip on a loaded developer machine while
# keeping the failure mode (a stuck WM) detectable.
_WM_REGISTRATION_TIMEOUT = 2.0
_WM_POLL_INTERVAL = 0.05


def _spawn_x11_window(
    display: Xlib.display.Display, width: int, height: int, pid: int
) -> _XWindow:
    """Map an ``InputOutput`` top-level with ``_NET_WM_PID`` set.

    Polls ``_NET_CLIENT_LIST`` until the WM has registered the window
    (or :data:`_WM_REGISTRATION_TIMEOUT` elapses). The backend's
    internal ``find_vrchat_window`` walk depends on this registration,
    so without the poll the focus/unfocus assertions race the WM.
    """
    screen = display.screen()
    window = screen.root.create_window(
        50,
        60,
        width,
        height,
        0,
        screen.root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=screen.white_pixel,
        event_mask=X.StructureNotifyMask,
    )
    net_wm_pid = display.intern_atom("_NET_WM_PID")
    window.change_property(net_wm_pid, Xatom.CARDINAL, 32, [pid])
    window.set_wm_name("vrcpilot-test")
    window.set_wm_class("vrcpilot-test", "vrcpilot-test")
    window.map()
    display.sync()

    net_client_list = display.intern_atom("_NET_CLIENT_LIST")
    deadline = time.monotonic() + _WM_REGISTRATION_TIMEOUT
    while time.monotonic() < deadline:
        prop = screen.root.get_full_property(net_client_list, X.AnyPropertyType)
        if prop is not None and window.id in list(prop.value):
            return window
        time.sleep(_WM_POLL_INTERVAL)
        display.sync()
    return window


@pytest.fixture
def x11_window() -> Iterator[None]:
    """Spawn a real top-level X11 window owned by this process.

    Yields once the WM has inserted the window into
    ``_NET_CLIENT_LIST`` with ``_NET_WM_PID == os.getpid()`` -- the
    exact condition the backend matches against. Window and display
    are torn down on teardown so other tests do not see a stray
    window.
    """
    display = open_x11_display()
    assert display is not None
    window = _spawn_x11_window(display, 320, 240, os.getpid())
    try:
        yield
    finally:
        try:
            window.destroy()
            display.sync()
        except Exception:
            pass
        display.close()


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

    def test_returns_true_for_existing_window(self, x11_window: None):
        # Real focus round-trip: spawn a top-level X11 window, send
        # the EWMH ``_NET_ACTIVE_WINDOW`` ClientMessage to the WM.
        # The WM may or may not honour the request (depends on
        # focus-stealing policy) but the helper's contract is to
        # return True once the message was successfully sent and
        # flushed -- which it will be on any cooperating EWMH WM.
        _ = x11_window

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

    def test_returns_true_for_existing_window(self, x11_window: None):
        # ``window.configure(stack_mode=X.Below)`` succeeds against
        # the live X11 window: the X server accepts the configure
        # request, the helper flushes, and returns True. We do not
        # assert the resulting z-order because that depends on which
        # other windows happen to be open on the runner.
        _ = x11_window

        assert unfocus_window(pid=os.getpid()) is True


class TestNativeWindowRectMatchesXlib:
    """The native ``get_window_rect`` must agree with the python-xlib helper
    that the (still-Python) capture backend uses.

    ``vrcpilot.geometry`` now reads the rect via the native x11rb path
    while ``vrcpilot.capture.linux`` still reads it via
    ``vrcpilot.linux.get_window_rect``. If the two disagree, mouse-click
    translation (geometry) drifts from the captured frame (capture). This
    pins them to the same value against a real X window -- in particular
    that the native path reproduces the sign convention of the xlib
    helper's ``translate_coords`` negation.
    """

    @pytest.mark.integration_real
    def test_native_rect_matches_xlib_helper(self):
        from vrcpilot import _native
        from vrcpilot.linux import get_window_rect as xlib_get_window_rect

        display = open_x11_display()
        assert display is not None
        window = _spawn_x11_window(display, 320, 240, os.getpid())
        try:
            xlib_rect = xlib_get_window_rect(display, window)
            native_rect = _native.window.get_window_rect(os.getpid())
        finally:
            try:
                window.destroy()
                display.sync()
            except Exception:
                pass
            display.close()

        assert xlib_rect is not None
        assert native_rect is not None
        assert tuple(native_rect) == tuple(xlib_rect)
