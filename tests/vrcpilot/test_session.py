"""Unit tests for :mod:`vrcpilot.session`.

``is_wayland_native`` is pure environment-variable inspection; every
test uses ``monkeypatch.setenv`` / ``delenv`` to drive the real
``os.environ`` lookup. No mocks of stdlib functions are needed because
``os.environ`` IS the input the spec talks about.
"""

from __future__ import annotations

import pytest

from vrcpilot.session import is_wayland_native


class TestIsWaylandNative:
    """Per the docstring, the function is true iff ``XDG_SESSION_TYPE ==
    "wayland"`` AND ``DISPLAY`` is absent/empty.

    XWayland (``DISPLAY=:0`` under a wayland session) must report False
    because X11 ops still work in that case.
    """

    def test_wayland_session_without_display_is_native(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("DISPLAY", raising=False)

        assert is_wayland_native() is True

    def test_wayland_session_with_display_is_not_native(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # XWayland: a DISPLAY socket is exported alongside the wayland
        # session so X11 clients keep working. Not "Wayland-native".
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setenv("DISPLAY", ":0")

        assert is_wayland_native() is False

    def test_empty_display_is_treated_as_unset(self, monkeypatch: pytest.MonkeyPatch):
        # ``DISPLAY=""`` is what shells produce after ``unset``-then-export.
        # It must not block native-wayland detection because X11 clients
        # themselves treat it as no-display.
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.setenv("DISPLAY", "")

        assert is_wayland_native() is True

    def test_x11_session_is_not_native(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.setenv("DISPLAY", ":0")

        assert is_wayland_native() is False

    def test_unset_session_type_is_not_native(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
        monkeypatch.delenv("DISPLAY", raising=False)

        assert is_wayland_native() is False

    def test_tty_session_type_is_not_native(self, monkeypatch: pytest.MonkeyPatch):
        # Any value other than "wayland" must report False, even with
        # no DISPLAY exported. Catches a regression where the function
        # checked only "DISPLAY is unset" without verifying the session type.
        monkeypatch.setenv("XDG_SESSION_TYPE", "tty")
        monkeypatch.delenv("DISPLAY", raising=False)

        assert is_wayland_native() is False
