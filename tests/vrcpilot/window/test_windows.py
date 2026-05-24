"""Tests for :mod:`vrcpilot.window.windows` (Win32 focus/unfocus backend).

The module under test imports Windows-only DLLs (``pywintypes``,
``win32gui``, ``win32api``) and raises ``ImportError`` on every other
platform. A module-level skip up front keeps non-Windows runners from
attempting the import.

Backend helpers now accept an explicit ``pid=`` (the public dispatch
layer in :mod:`vrcpilot.window` resolves the PID). Tests pass either
an unused PID -- exercising the "window not found" branch against the
real ``find_vrchat_hwnd`` -- or the live tkinter window's PID --
exercising the full focus/unfocus/is_foreground round-trip against the
live Win32 API. No internal-function or Win32-surface mocking is used.
"""

from __future__ import annotations

import os
import sys

import pytest

if sys.platform != "win32":
    pytest.skip("vrcpilot.window.windows is Windows-only", allow_module_level=True)

from tests.helpers import has_working_tkinter  # noqa: E402

if not has_working_tkinter():
    pytest.skip(
        "tkinter cannot initialize Tk on this host (broken Tcl/Tk install)",
        allow_module_level=True,
    )

import tkinter
from collections.abc import Iterator

from vrcpilot.window.windows import (
    focus_window,
    is_window_foreground,
    unfocus_window,
)

_UNUSED_PID = 99_999_999


@pytest.fixture
def tk_window() -> Iterator[tkinter.Tk]:
    """Spawn a real Tk top-level window mapped on the Windows desktop.

    ``update()`` forces the WM round-trip so the window shows up in
    ``EnumWindows`` with a valid HWND owned by ``os.getpid()`` --
    which is the PID the backend will look up. Destroyed on teardown.

    The ``tkinter.Tk()`` call is wrapped in a try/except as a defensive
    fallback: ``has_working_tkinter()`` at module level should already
    skip the module on hosts where Tcl/Tk is broken, but the probe
    caches its result and some Windows CI runners exhibit a flaky
    "first Tk() works, second one raises" mode -- so we re-check here
    and skip the individual test rather than erroring out.
    """
    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:
        pytest.skip(f"tkinter.Tk() failed at fixture time: {exc}")
    root.geometry("320x240+50+60")
    root.update_idletasks()
    root.update()
    try:
        yield root
    finally:
        root.destroy()


class TestFocusWindow:
    def test_returns_false_when_no_window_owns_pid(self):
        # Real ``EnumWindows`` walk against the live OS. No window owns
        # ``_UNUSED_PID`` so ``find_vrchat_hwnd`` returns ``None`` and
        # the helper short-circuits to False without invoking any Win32
        # state-changing API.
        assert focus_window(pid=_UNUSED_PID) is False

    def test_returns_true_for_existing_window(self, tk_window: tkinter.Tk):
        # Real focus round-trip: spawn a tk window, ask the backend to
        # focus it. ``SetForegroundWindow`` succeeds for windows owned
        # by the current process, so the helper must report True.
        # (Cross-process focus is subject to Windows' foreground lock
        # which is out of scope here -- see e2e suite for VRChat.)
        _ = tk_window  # keep window alive for the duration of the call

        assert focus_window(pid=os.getpid()) is True


class TestIsWindowForeground:
    def test_returns_false_when_no_window_owns_pid(self):
        # Without an owning HWND there is nothing to compare against
        # ``GetForegroundWindow`` -- helper must report False without
        # calling the API.
        assert is_window_foreground(pid=_UNUSED_PID) is False

    def test_returns_true_after_focusing_window(self, tk_window: tkinter.Tk):
        # Focus the tk window then immediately ask whether it owns the
        # foreground. Both calls hit the live Win32 API; this pins the
        # contract that ``is_foreground`` agrees with the result of
        # ``focus`` for windows owned by the current process.
        _ = tk_window
        assert focus_window(pid=os.getpid()) is True

        assert is_window_foreground(pid=os.getpid()) is True


class TestUnfocusWindow:
    def test_returns_false_when_no_window_owns_pid(self):
        # Real ``EnumWindows`` walk; nothing to unfocus -> False.
        assert unfocus_window(pid=_UNUSED_PID) is False

    def test_returns_true_for_existing_window(self, tk_window: tkinter.Tk):
        # ``SetWindowPos(HWND_BOTTOM, SWP_NOACTIVATE)`` succeeds against
        # the live HWND, so the helper must report True. We do not
        # assert post-call z-order because that depends on which other
        # windows happen to be open on the runner.
        _ = tk_window

        assert unfocus_window(pid=os.getpid()) is True
