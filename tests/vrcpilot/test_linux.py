"""Tests for :mod:`vrcpilot.linux` (X11 helpers).

The module under test raises ``ImportError`` on non-Linux platforms and
the real paths require a reachable X server. Two module-level skips up
front gate the rest of the file: platform first, then display
reachability. Below the gate every test uses a real
``Xlib.display.Display()`` connection -- no 3rd-party-Xlib mocks,
no fake X displays -- so behaviour observed here is exactly what
production runs against.

The geometry tests spawn a real Tk top-level window with a known
size, locate it via ``_NET_WM_PID == os.getpid()``, and compare the
reported rectangle against the requested dimensions. This is the
integration-real pattern for X11: tkinter is in the stdlib so no
extra dependency is needed, and the WM round-trip exercises the
exact code path that runs against VRChat at runtime.
"""

from __future__ import annotations

import os
import sys

import pytest

if sys.platform != "linux":
    pytest.skip("vrcpilot.linux is Linux-only", allow_module_level=True)

from tests.helpers import has_x11_display

if not has_x11_display():
    pytest.skip("X11 display unavailable", allow_module_level=True)

import tkinter
from collections.abc import Iterator

from vrcpilot.linux import (
    find_vrchat_window,
    get_window_rect,
    open_x11_display,
    x11_display,
)


@pytest.fixture
def tk_window() -> Iterator[tuple[tkinter.Tk, int, int]]:
    """Spawn a real Tk top-level window mapped on the X display.

    Yields ``(root, width, height)`` where the window has been forced
    through ``update_idletasks()`` so the WM has assigned a frame and
    ``_NET_WM_PID`` is populated. The window owner PID equals
    ``os.getpid()``, so ``find_vrchat_window`` (which matches on
    ``_NET_WM_PID``) can discover it. Destroyed on teardown so other
    tests do not see a stray window.
    """
    root = tkinter.Tk()
    width, height = 320, 240
    root.geometry(f"{width}x{height}+50+60")
    root.update_idletasks()
    root.update()
    try:
        yield root, width, height
    finally:
        root.destroy()


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

    def test_locates_window_by_net_wm_pid(self, tk_window: tuple[tkinter.Tk, int, int]):
        # Real round-trip: a tkinter window with PID == os.getpid() is
        # present in ``_NET_CLIENT_LIST``, the helper enumerates the
        # list, matches the ``_NET_WM_PID`` property, and returns the
        # window object. This is the exact production code path that
        # locates VRChat at runtime.
        _root, _w, _h = tk_window
        display = open_x11_display()
        assert display is not None
        try:
            found = find_vrchat_window(display, os.getpid())
            assert found is not None
        finally:
            display.close()


class TestGetWindowRect:
    def test_returns_window_dimensions_for_real_window(
        self, tk_window: tuple[tkinter.Tk, int, int]
    ):
        # Real geometry round-trip: ask Tk for a 320x240 window, then
        # the production helper must report a rectangle whose width and
        # height match. Position is WM-dependent (frame decorations,
        # reparenting) so only the size is pinned.
        _root, width, height = tk_window
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
        # propagate. We drive this by creating a real Tk window,
        # locating it, destroying it, then asking for its geometry --
        # exactly the race condition the production handler exists for.
        root = tkinter.Tk()
        root.geometry("200x100+10+10")
        root.update_idletasks()
        root.update()

        display = open_x11_display()
        assert display is not None
        try:
            window = find_vrchat_window(display, os.getpid())
            assert window is not None
            root.destroy()
            # ``Display.sync()`` forces the destruction notification to
            # round-trip before we ask for the geometry; without it the
            # window may still appear live to the next request.
            display.sync()

            assert get_window_rect(display, window) is None
        finally:
            try:
                # Best-effort cleanup if the test failed before destroy.
                root.destroy()
            except tkinter.TclError:
                pass
            display.close()
