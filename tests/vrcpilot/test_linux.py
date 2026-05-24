"""Tests for :mod:`vrcpilot.linux` (X11 helpers).

The module under test raises ``ImportError`` on non-Linux platforms and
the real paths require a reachable X server. Two module-level skips up
front gate the rest of the file: platform first, then display
reachability. Below the gate every test uses a real
``Xlib.display.Display()`` connection -- no 3rd-party-Xlib mocks,
no fake X displays -- so behaviour observed here is exactly what
production runs against.

The geometry tests spawn a real X11 top-level window via raw Xlib
calls (rather than ``tkinter``) because EWMH-compliant WMs such as
Mutter only insert toolkit-decorated top-levels into
``_NET_CLIENT_LIST`` after a reparent dance that does not propagate
``_NET_WM_PID`` onto the frame -- so a tk window with the correct
``_NET_WM_PID`` set on its content sub-window is invisible to the
production walk. A bare ``InputOutput`` window we open ourselves goes
straight into ``_NET_CLIENT_LIST`` with ``_NET_WM_PID`` intact, which
is exactly what VRChat's main window looks like to the WM at runtime.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator

import pytest

if sys.platform != "linux":
    pytest.skip("vrcpilot.linux is Linux-only", allow_module_level=True)

from tests.helpers import has_x11_display

if not has_x11_display():
    pytest.skip("X11 display unavailable", allow_module_level=True)

import Xlib.display
from Xlib import X, Xatom
from Xlib.xobject.drawable import Window as _XWindow

from vrcpilot.linux import (
    find_vrchat_window,
    get_window_rect,
    open_x11_display,
    x11_display,
)

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
    (or :data:`_WM_REGISTRATION_TIMEOUT` elapses). This is the
    integration-real equivalent of "VRChat has started and the WM has
    finished its bookkeeping" -- without the poll the production walk
    races the WM and intermittently misses the window.
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
    pytest.skip(
        f"WM did not register window in _NET_CLIENT_LIST within "
        f"{_WM_REGISTRATION_TIMEOUT}s -- the host WM is likely not "
        f"EWMH-compliant or is overloaded; skipping rather than racing"
    )


@pytest.fixture
def x11_window() -> Iterator[tuple[Xlib.display.Display, _XWindow, int, int]]:
    """Spawn a real top-level X11 window mapped on the display.

    Yields ``(display, window, width, height)`` once the WM has
    inserted the window into ``_NET_CLIENT_LIST`` with
    ``_NET_WM_PID == os.getpid()`` -- which is the exact condition
    ``find_vrchat_window`` matches against. Window and display are
    torn down on teardown so other tests do not see a stray window.
    """
    display = open_x11_display()
    assert display is not None
    width, height = 320, 240
    window = _spawn_x11_window(display, width, height, os.getpid())
    try:
        yield display, window, width, height
    finally:
        try:
            window.destroy()
            display.sync()
        except Exception:
            pass
        display.close()


class TestOpenX11Display:
    def test_returns_real_display_when_x_server_reachable(self):
        # The module-level guard already proved a display is reachable;
        # this test pins the contract that the helper produces a usable
        # ``Display`` object (``screen()`` is the cheapest sanity probe)
        # rather than some other truthy stand-in.
        display = open_x11_display()

        assert display is not None
        try:
            assert display.screen() is not None
        finally:
            display.close()

    def test_returns_none_when_display_env_var_invalid(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # ``"garbage"`` is not a parseable DISPLAY string, so the real
        # ``Xlib.display.Display()`` constructor raises
        # ``Xlib.error.DisplayNameError`` -- the helper must surface
        # ``None`` rather than propagate.
        monkeypatch.setenv("DISPLAY", "garbage")

        assert open_x11_display() is None


class TestX11DisplayContextManager:
    def test_yields_usable_display_inside_with_block(self):
        # Inside the ``with`` block the yielded value must be a live
        # ``Display`` ready for use. After exit it is closed; we do not
        # assert post-close state because the real ``Display.close()``
        # is idempotent and observable state is implementation-defined.
        with x11_display() as display:
            assert display is not None
            assert display.screen() is not None

    def test_yields_none_when_display_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # Same connection-failure path as ``open_x11_display`` but
        # routed through the context-manager helper so callers using
        # ``with`` get the same ``None`` sentinel rather than an
        # exception inside the block.
        monkeypatch.setenv("DISPLAY", "garbage")

        with x11_display() as display:
            assert display is None


class TestFindVrchatWindow:
    def test_returns_none_when_no_window_owns_pid(self):
        # Empty client list match: no window owns the unused PID, so
        # the WM client-list walk completes without a hit and returns
        # ``None``. ``99_999_999`` is preferred over ``-1`` because
        # some Xlib paths reject negative PIDs early.
        display = open_x11_display()
        assert display is not None
        try:
            assert find_vrchat_window(display, 99_999_999) is None
        finally:
            display.close()

    def test_locates_window_by_net_wm_pid(
        self, x11_window: tuple[Xlib.display.Display, _XWindow, int, int]
    ):
        # Real round-trip: a top-level X11 window with PID ==
        # os.getpid() is present in ``_NET_CLIENT_LIST``, the helper
        # enumerates the list, matches the ``_NET_WM_PID`` property,
        # and returns the window object. This is the exact production
        # code path that locates VRChat at runtime.
        _display, _window, _w, _h = x11_window
        display = open_x11_display()
        assert display is not None
        try:
            found = find_vrchat_window(display, os.getpid())
            assert found is not None
        finally:
            display.close()


class TestGetWindowRect:
    def test_returns_window_dimensions_for_real_window(
        self, x11_window: tuple[Xlib.display.Display, _XWindow, int, int]
    ):
        # Real geometry round-trip: ask the X server for a 320x240
        # window, then the production helper must report a rectangle
        # whose width and height match. Position is WM-dependent
        # (frame decorations, reparenting) so only the size is pinned.
        _display, _spawned, width, height = x11_window
        display = open_x11_display()
        assert display is not None
        try:
            window = find_vrchat_window(display, os.getpid())
            assert window is not None
            rect = get_window_rect(display, window)
        finally:
            display.close()

        assert rect is not None
        _x, _y, w, h = rect
        assert w == width
        assert h == height

    def test_returns_none_after_window_destroyed(self):
        # Window destroyed mid-call: the production code catches the
        # resulting ``XError`` and returns ``None`` rather than
        # propagate. We drive this by creating a real X11 window,
        # locating it, destroying it, then asking for its geometry --
        # exactly the race condition the production handler exists for.
        spawner_display = open_x11_display()
        assert spawner_display is not None
        spawned = _spawn_x11_window(spawner_display, 200, 100, os.getpid())

        display = open_x11_display()
        assert display is not None
        try:
            window = find_vrchat_window(display, os.getpid())
            assert window is not None
            spawned.destroy()
            spawner_display.sync()
            # ``Display.sync()`` forces the destruction notification to
            # round-trip before we ask for the geometry; without it the
            # window may still appear live to the next request.
            display.sync()

            assert get_window_rect(display, window) is None
        finally:
            try:
                # Best-effort cleanup if the test failed before destroy.
                spawned.destroy()
                spawner_display.sync()
            except Exception:
                pass
            spawner_display.close()
            display.close()
