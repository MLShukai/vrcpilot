"""Tests for :mod:`vrcpilot.geometry`.

``get_vrchat_window_rect`` is the public entry point; it resolves the
PID via :func:`vrcpilot.process.resolve_pid` then dispatches to the
platform backend. The autouse ``_no_real_vrchat`` fixture in
:mod:`tests.conftest` ensures :func:`vrcpilot.process.find_pids`
returns ``[]``, so ``resolve_pid(None)`` raises
:class:`VRChatNotRunningError` and the helper returns ``None`` on every
host without a live VRChat.

The backend integration tests pass an unused-but-syntactically-valid
PID (``99_999_999``) so ``resolve_pid`` short-circuits the
``pid is not None`` branch without consulting ``find_pids``. The real
platform backend then runs against the live OS, looks for a window
owned by that PID, finds none, and returns ``None`` -- exercising the
full code path with zero internal-function mocking. ``-1`` is avoided
because some Linux ``_NET_WM_PID`` readers reject negative values.
"""

from __future__ import annotations

import pytest

from tests.helpers import only_linux, only_windows, requires_x11_display
from vrcpilot.geometry import get_vrchat_window_rect

#: Syntactically valid PID guaranteed not to own any window on the test
#: host. The real backend's window-walk returns ``None`` for it without
#: any mocks, so we can drive the "VRChat not running" branch end-to-end
#: by passing this value as ``pid=``.
_UNUSED_PID = 99_999_999


class TestGetVrchatWindowRectShortCircuit:
    """Cross-platform: no VRChat -> ``None`` regardless of backend."""

    def test_returns_none_when_resolve_pid_finds_no_vrchat(self):
        # Autouse ``_no_real_vrchat`` leaves ``find_pids() == []`` so
        # ``resolve_pid(None)`` raises ``VRChatNotRunningError``. The
        # helper must catch that and return ``None`` rather than
        # propagate. Cross-platform; works on every supported host
        # without a display.
        assert get_vrchat_window_rect() is None


class TestGetVrchatWindowRectWindowsBackend:
    """Win32 backend integration: real ``EnumWindows`` walk."""

    @only_windows
    def test_returns_none_when_no_window_owned_by_pid(self):
        # PID is forwarded through ``resolve_pid`` unchanged and the
        # real ``find_vrchat_hwnd`` walks ``EnumWindows`` looking for
        # the visible top-level HWND owned by that PID. No such window
        # exists -> the backend reports ``None``.
        assert get_vrchat_window_rect(pid=_UNUSED_PID) is None


class TestGetVrchatWindowRectLinuxBackend:
    """X11 backend integration: real ``_NET_CLIENT_LIST`` walk."""

    @only_linux
    @requires_x11_display
    def test_returns_none_when_no_window_owned_by_pid(self):
        # Real ``open_x11_display()`` opens a live X server connection,
        # ``find_vrchat_window`` walks the WM client list looking for
        # ``_NET_WM_PID`` matches, and returns ``None`` because nothing
        # owns the unused PID. No mocks involved.
        assert get_vrchat_window_rect(pid=_UNUSED_PID) is None

    @only_linux
    def test_returns_none_when_x_display_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # ``DISPLAY=garbage`` forces ``Xlib.display.Display()`` to raise
        # ``DisplayNameError`` -> ``open_x11_display()`` returns ``None``
        # -> backend reports ``None``. Drives the unreachable-display
        # branch with zero mocks via real environment manipulation, and
        # runs on Linux hosts both with and without a real X display.
        monkeypatch.setenv("DISPLAY", "garbage")

        assert get_vrchat_window_rect(pid=_UNUSED_PID) is None
