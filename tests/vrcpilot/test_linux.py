"""Tests for :mod:`vrcpilot.x11`.

The module under test raises ``ImportError`` on non-Linux platforms,
and the real connection paths require a reachable X server. Two
module-level skips up front gate the rest of the file: platform
first, then display reachability. Below the gate, normal-path tests
exercise the real ``Xlib.display.Display()``; failure-path tests use
``FakeXDisplay`` from :mod:`tests.fakes` to drive ``XError``
branches without a fragile real-X11 setup.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "linux":
    pytest.skip("Linux-only module", allow_module_level=True)

from tests.helpers import has_x11_display

if not has_x11_display():
    pytest.skip("X11 display unavailable", allow_module_level=True)

from tests.fakes import (
    FakeXDisplay,
    FakeXGeometry,
    FakeXWindow,
    make_xerror_subclass,
)
from vrcpilot.x11 import (
    find_vrchat_window,
    get_window_rect,
    open_x11_display,
    x11_display,
)


class TestOpenX11Display:
    def test_returns_real_display_on_success(self):
        # The autouse env on this host has a reachable X server (the
        # module-level guard above ensures this), so the helper should
        # produce a live ``Display`` object.
        display = open_x11_display()

        assert display is not None
        try:
            # ``screen()`` is the cheapest call that proves we got a
            # working display rather than some other truthy stand-in.
            assert display.screen() is not None
        finally:
            display.close()

    def test_returns_none_when_display_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # ``"garbage"`` is not a parseable DISPLAY string, so the real
        # ``Xlib.display.Display()`` constructor raises
        # ``Xlib.error.DisplayError`` — driving the failure branch with
        # zero mocks and zero environment-dependent flakiness.
        monkeypatch.setenv("DISPLAY", "garbage")

        assert open_x11_display() is None


class TestX11DisplayContextManager:
    def test_yields_display_and_closes(self):
        with x11_display() as display:
            assert display is not None
            assert display.screen() is not None
        # After exit the connection has been closed; calling close again
        # on a real ``Display`` is a no-op so we do not assert state
        # here — the contract verified is that the ``with`` block
        # produced a usable display.

    def test_yields_none_on_connection_failure(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DISPLAY", "garbage")

        with x11_display() as display:
            assert display is None


class TestFindVrchatWindow:
    """Live ``Xlib`` walk over ``_NET_CLIENT_LIST``; VRChat is not running
    (autouse fixture forces ``find_pid()`` to ``None``), so the helper must
    report ``None`` whatever windows the desktop happens to have open."""

    def test_returns_none_when_no_window_owns_pid(self):
        display = open_x11_display()
        assert display is not None
        try:
            # ``-1`` is never a valid PID, so even a populated client
            # list will produce no match.
            assert find_vrchat_window(display, -1) is None
        finally:
            display.close()


class TestGetWindowRect:
    """Failure-path tests use FakeXDisplay rather than a fragile real-X11 setup
    to drive degenerate-geometry and XError branches.

    The success path depends on a specific real window's geometry and
    is covered end-to-end by the e2e scenarios under
    ``tests/e2e/`` rather than re-stubbed here.
    """

    def test_returns_none_on_xerror(self):
        # ``XError`` covers any X protocol failure during the lookup;
        # the FakeXWindow's ``raises`` channel injects exactly such a
        # failure on the first method call.
        xerror_cls = make_xerror_subclass()
        fake_display = FakeXDisplay()
        fake_window = FakeXWindow(raises=xerror_cls())

        assert get_window_rect(fake_display, fake_window) is None  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("width", "height"),
        [(0, 50), (100, 0), (-1, 50), (100, -1), (0, 0)],
    )
    def test_returns_none_on_degenerate_geometry(self, width: int, height: int):
        fake_display = FakeXDisplay()
        fake_window = FakeXWindow(geometry=FakeXGeometry(width=width, height=height))

        assert get_window_rect(fake_display, fake_window) is None  # type: ignore[arg-type]

    def test_sign_flips_translate_coords(self):
        # Documents the empirical sign-flip behaviour (see source
        # docstring + commit ``77a6422``): translate_coords reports the
        # negated origin under python-xlib, so the helper inverts it.
        fake_display = FakeXDisplay()
        fake_window = FakeXWindow(
            geometry=FakeXGeometry(width=800, height=600),
            translate_coords=(-100, -200),
        )

        assert get_window_rect(fake_display, fake_window) == (  # type: ignore[arg-type]
            100,
            200,
            800,
            600,
        )
