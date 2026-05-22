"""Tests for :mod:`vrcpilot.capture.linux`.

The module raises ``ImportError`` on non-Linux because it depends on
``Xlib``, so a module-level skip up front gates the rest of the file.
Below the gate, the autouse ``_no_real_vrchat`` fixture in
:mod:`tests.conftest` pins ``find_pid()`` to ``None`` so the "VRChat
not running" branch is exercised with zero explicit mocks.

These tests never open a real X display; ``open_x11_display`` is
patched with :class:`tests.fakes.FakeXDisplay` so we can assert
``close()`` is invoked when init aborts — otherwise the X server
socket leaks across each retry. (Lifecycle tests that need a real
frame are in ``test_session.py`` and use the public ``Capture``.)
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "linux":
    pytest.skip("Linux-only module", allow_module_level=True)

from dataclasses import dataclass

from pytest_mock import MockerFixture

from tests.fakes import FakeXDisplay, FakeXWindow, make_xerror_subclass
from vrcpilot.capture.linux import X11CaptureBackend


@dataclass
class _X11Chain:
    """Bundle of fakes wired in by :func:`x11_chain`."""

    display: FakeXDisplay
    window: FakeXWindow


@pytest.fixture
def x11_chain(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> _X11Chain:
    """Patch the find/open/lookup chain past the early VRChat-running check.

    Returns the ``FakeXDisplay`` and ``FakeXWindow`` so each test can
    assert against them or override one entry (e.g. set
    ``find_vrchat_window`` to ``None``) without re-stating the
    boilerplate. ``DISPLAY`` is also set so ``is_wayland_native()``
    reports ``False``.
    """
    monkeypatch.setenv("DISPLAY", ":0")
    fake_display = FakeXDisplay()
    fake_window = FakeXWindow()
    mocker.patch("vrcpilot.capture.linux.find_pid", return_value=4242)
    mocker.patch("vrcpilot.capture.linux.open_x11_display", return_value=fake_display)
    mocker.patch("vrcpilot.capture.linux.find_vrchat_window", return_value=fake_window)
    return _X11Chain(display=fake_display, window=fake_window)


class TestX11CaptureBackend:
    def test_raises_on_wayland_native(self, monkeypatch: pytest.MonkeyPatch):
        # Continuous capture is fail-fast on native Wayland because
        # there is no fallback; XWayland sessions still expose DISPLAY
        # and pass through.
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("DISPLAY", raising=False)

        with pytest.raises(RuntimeError, match="native Wayland is not supported"):
            X11CaptureBackend()

    def test_raises_when_vrchat_not_running(self, monkeypatch: pytest.MonkeyPatch):
        # Autouse fixture pins ``find_pid()`` to ``None``; the backend
        # must surface this as RuntimeError before opening a display.
        monkeypatch.setenv("DISPLAY", ":0")

        with pytest.raises(RuntimeError, match="VRChat is not running"):
            X11CaptureBackend()

    def test_raises_when_display_unavailable(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ):
        # ``open_x11_display`` returns ``None`` when XOpenDisplay fails;
        # the backend converts this to RuntimeError so callers do not
        # need to read the docs of the helper.
        monkeypatch.setenv("DISPLAY", ":0")
        mocker.patch("vrcpilot.capture.linux.find_pid", return_value=4242)
        mocker.patch("vrcpilot.capture.linux.open_x11_display", return_value=None)

        with pytest.raises(RuntimeError, match="X11 display unavailable"):
            X11CaptureBackend()

    def test_closes_display_when_window_not_found(
        self, mocker: MockerFixture, x11_chain: _X11Chain
    ):
        # Override the chain's ``find_vrchat_window`` to None so the
        # close-on-failure path runs.
        mocker.patch("vrcpilot.capture.linux.find_vrchat_window", return_value=None)

        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            X11CaptureBackend()
        assert x11_chain.display.close_calls == 1

    def test_closes_display_on_composite_xerror(
        self, mocker: MockerFixture, x11_chain: _X11Chain
    ):
        # When the Composite extension is missing the server raises an
        # XError on ``query_version``. We must wrap as RuntimeError and
        # close the display so the retry loop above cannot leak.
        xerr_cls = make_xerror_subclass()
        mocker.patch(
            "vrcpilot.capture.linux.composite.query_version",
            side_effect=xerr_cls(),
        )

        with pytest.raises(RuntimeError, match="X11 Composite extension"):
            X11CaptureBackend()
        assert x11_chain.display.close_calls == 1

    def test_closes_display_on_redirect_xerror(
        self, mocker: MockerFixture, x11_chain: _X11Chain
    ):
        # ``redirect_window`` may raise on locked-down servers (XACE,
        # nested Xephyr, etc.). Same recovery contract: wrap and close
        # the display.
        mocker.patch("vrcpilot.capture.linux.composite.query_version")
        xerr_cls = make_xerror_subclass()
        mocker.patch(
            "vrcpilot.capture.linux.composite.redirect_window",
            side_effect=xerr_cls(),
        )

        with pytest.raises(RuntimeError, match="Failed to redirect window"):
            X11CaptureBackend()
        assert x11_chain.display.close_calls == 1
