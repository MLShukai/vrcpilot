"""Tests for :mod:`vrcpilot.window` (top-level platform dispatch).

The dispatch layer's job is to:

* short-circuit to ``False`` when ``resolve_pid()`` reports that VRChat
  is not running, and
* forward the resolved ``pid`` to the active-platform backend.

The autouse ``_no_real_vrchat`` fixture in :mod:`tests.conftest` leaves
``find_pids() == []`` so the first contract is exercised with no
mocking. The second contract is exercised by passing an unused PID
explicitly: ``resolve_pid(non_None)`` returns the value unchanged,
the dispatch forwards it to the live backend, the backend's real
window walk finds nothing, and the function reports ``False`` --
exactly the observable contract.

Backend internals (Win32 / X11 specifics) are tested in
``test_windows.py`` / ``test_linux.py``. This file pins only the
dispatch surface.
"""

from __future__ import annotations

import sys
import warnings

import pytest

import vrcpilot.window

#: Syntactically valid PID guaranteed not to own any window on the
#: test host. ``resolve_pid`` short-circuits on ``pid is not None``
#: so this exercises the dispatch + backend path without consulting
#: ``find_pids``.
_UNUSED_PID = 99_999_999


@pytest.fixture(autouse=True)
def _require_supported_platform():
    # Outside Windows/Linux ``import vrcpilot`` itself would have
    # raised ImportError before this test module loaded, so this guard
    # is defensive against accidental future-platform CI runners.
    if sys.platform not in ("win32", "linux"):
        pytest.skip("vrcpilot.window dispatch only wired for Windows and Linux")


class TestFocus:
    def test_returns_false_when_vrchat_not_running(self):
        # Autouse ``_no_real_vrchat`` leaves ``find_pids() == []``, so
        # ``resolve_pid(None)`` raises ``VRChatNotRunningError``. The
        # dispatch must catch that and return False rather than
        # propagate. Linux backend may emit a Wayland warning if the
        # host happens to be in that state -- suppress so the test is
        # not host-dependent.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert vrcpilot.window.focus() is False

    def test_returns_false_when_explicit_pid_owns_no_window(self):
        # PID forwarded through ``resolve_pid(_UNUSED_PID) == _UNUSED_PID``
        # to the live backend (Win32 EnumWindows / X11 client-list walk).
        # No window owns the PID -> backend returns False -> dispatch
        # returns False. End-to-end integration with no mocking.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert vrcpilot.window.focus(pid=_UNUSED_PID) is False


class TestIsForeground:
    def test_returns_false_when_vrchat_not_running(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert vrcpilot.window.is_foreground() is False

    def test_returns_false_when_explicit_pid_owns_no_window(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert vrcpilot.window.is_foreground(pid=_UNUSED_PID) is False


class TestUnfocus:
    def test_returns_false_when_vrchat_not_running(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert vrcpilot.window.unfocus() is False

    def test_returns_false_when_explicit_pid_owns_no_window(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert vrcpilot.window.unfocus(pid=_UNUSED_PID) is False
