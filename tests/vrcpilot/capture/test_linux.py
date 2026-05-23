"""Tests for :mod:`vrcpilot.capture.linux`.

The module raises ``ImportError`` on non-Linux because it depends on
``Xlib``, so a module-level skip up front gates the rest of the file.
``X11CaptureBackend`` now requires ``pid`` as a keyword argument; PID
resolution lives one layer up in :class:`vrcpilot.capture.Capture`, so
each test passes a concrete PID explicitly.

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
    """Patch the display/window lookup chain past the Wayland check.

    Returns the ``FakeXDisplay`` and ``FakeXWindow`` so each test can
    assert against them or override one entry (e.g. set
    ``find_vrchat_window`` to ``None``) without re-stating the
    boilerplate. ``DISPLAY`` is also set so ``is_wayland_native()``
    reports ``False``.
    """
    monkeypatch.setenv("DISPLAY", ":0")
    fake_display = FakeXDisplay()
    fake_window = FakeXWindow()
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
            X11CaptureBackend(pid=4242)

    def test_raises_when_display_unavailable(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ):
        # ``open_x11_display`` returns ``None`` when XOpenDisplay fails;
        # the backend converts this to RuntimeError so callers do not
        # need to read the docs of the helper.
        monkeypatch.setenv("DISPLAY", ":0")
        mocker.patch("vrcpilot.capture.linux.open_x11_display", return_value=None)

        with pytest.raises(RuntimeError, match="X11 display unavailable"):
            X11CaptureBackend(pid=4242)

    def test_closes_display_when_window_not_found(
        self, mocker: MockerFixture, x11_chain: _X11Chain
    ):
        # Override the chain's ``find_vrchat_window`` to None so the
        # close-on-failure path runs.
        mocker.patch("vrcpilot.capture.linux.find_vrchat_window", return_value=None)

        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            X11CaptureBackend(pid=4242)
        assert x11_chain.display.close_calls == 1

    def test_pid_is_forwarded_to_find_vrchat_window(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ):
        # The backend must thread the caller-provided PID into
        # ``find_vrchat_window`` so multi-instance disambiguation
        # (handled by ``resolve_pid`` one layer up) actually targets
        # the right X window. We deliberately make the lookup fail so
        # the backend short-circuits before touching Composite.
        monkeypatch.setenv("DISPLAY", ":0")
        fake_display = FakeXDisplay()
        mocker.patch(
            "vrcpilot.capture.linux.open_x11_display", return_value=fake_display
        )
        find_window = mocker.patch(
            "vrcpilot.capture.linux.find_vrchat_window", return_value=None
        )
        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            X11CaptureBackend(pid=98765)
        assert find_window.call_args is not None
        args, _kwargs = find_window.call_args
        assert args[1] == 98765

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
            X11CaptureBackend(pid=4242)
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
            X11CaptureBackend(pid=4242)
        assert x11_chain.display.close_calls == 1
