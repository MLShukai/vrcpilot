"""Integration-real tests for :mod:`vrcpilot.windows` (Win32 helpers).

The module under test imports Windows-only DLLs (``pywintypes``,
``win32gui``, ``win32process``) and raises ``ImportError`` on every
other platform. A module-level skip up front prevents non-Windows
runners from even attempting the import -- everything below executes
only on a Windows host.

The geometry tests spawn a real Tk top-level window with a known
size, then locate its HWND via ``EnumWindows`` matching on
``os.getpid()`` and compare the reported rectangle against the
requested dimensions. This is the integration-real pattern for
Win32: tkinter is in the stdlib so no extra dependency is needed,
and the WM round-trip exercises the exact code path that runs
against VRChat at runtime.
"""

from __future__ import annotations

import os
import sys

import pytest

if sys.platform != "win32":
    pytest.skip("vrcpilot.windows is Windows-only", allow_module_level=True)

from tests.helpers import has_working_tkinter  # noqa: E402

if not has_working_tkinter():
    pytest.skip(
        "tkinter cannot initialize Tk on this host (broken Tcl/Tk install)",
        allow_module_level=True,
    )

import tkinter
from collections.abc import Iterator

import win32gui

from vrcpilot.windows import find_vrchat_hwnd, get_window_rect


@pytest.fixture
def tk_window() -> Iterator[tuple[tkinter.Tk, int, int]]:
    """Spawn a real Tk top-level window with a known size.

    Yields ``(root, width, height)``. ``update()`` forces the window
    through the WM so it shows up in ``EnumWindows`` with the requested
    geometry. The owner PID equals ``os.getpid()``, which is what
    ``find_vrchat_hwnd`` matches against. Destroyed on teardown so
    other tests do not see a stray window.

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
    width, height = 320, 240
    root.geometry(f"{width}x{height}+50+60")
    root.update_idletasks()
    root.update()
    try:
        yield root, width, height
    finally:
        root.destroy()


class TestFindVrchatHwnd:
    def test_returns_none_for_unknown_pid(self):
        # Real ``EnumWindows`` walk. ``-1`` is never a valid Windows
        # PID, so even on a fully populated desktop the helper must
        # report ``None`` rather than raise.
        assert find_vrchat_hwnd(-1) is None

    def test_locates_visible_top_level_window_by_pid(
        self, tk_window: tuple[tkinter.Tk, int, int]
    ):
        # Real round-trip: a tkinter window owned by ``os.getpid()`` is
        # enumerated by ``EnumWindows``, its PID matches via
        # ``GetWindowThreadProcessId``, ``IsWindowVisible`` is True, so
        # the helper returns its HWND. This is the exact production
        # path that locates VRChat at runtime.
        _root, _w, _h = tk_window

        hwnd = find_vrchat_hwnd(os.getpid())

        assert hwnd is not None
        assert hwnd > 0


class TestGetWindowRect:
    def test_returns_none_for_invalid_hwnd(self):
        # ``0`` is not a valid HWND. The underlying ``GetWindowRect``
        # call raises ``pywintypes.error`` for it; the helper must
        # convert that to ``None`` and not propagate.
        assert get_window_rect(0) is None

    def test_returns_window_dimensions_for_real_hwnd(
        self, tk_window: tuple[tkinter.Tk, int, int]
    ):
        # ``get_window_rect`` returns the *outer* rect (title bar +
        # borders included) because production uses it as the mss /
        # windows-capture grab region for VRChat -- not the client area.
        # We can't compare against ``Tk.geometry()`` directly (Tk sets
        # client size) so use Win32's ``GetWindowRect`` /
        # ``GetClientRect`` as independent oracles: pin the outer dims
        # exactly against the WM, and verify the WM-reported client size
        # is at least the requested Tk size (Tk is DPI-unaware so the
        # WM may scale the client up on high-DPI hosts).
        _root, client_w, client_h = tk_window
        hwnd = find_vrchat_hwnd(os.getpid())
        assert hwnd is not None

        cleft, ctop, cright, cbottom = win32gui.GetClientRect(hwnd)
        wm_client_w = cright - cleft
        wm_client_h = cbottom - ctop
        oleft, otop, oright, obottom = win32gui.GetWindowRect(hwnd)
        wm_outer_w = oright - oleft
        wm_outer_h = obottom - otop

        rect = get_window_rect(hwnd)

        assert rect is not None
        _x, _y, w, h = rect
        # Production must report the outer rect (what mss.grab expects).
        assert (w, h) == (wm_outer_w, wm_outer_h)
        # Independent invariant: the WM client size is at least what Tk
        # asked for, modulo per-monitor DPI scaling.
        assert wm_client_w >= client_w
        assert wm_client_h >= client_h

    def test_returns_none_after_window_destroyed(self):
        # Window destroyed mid-call: ``GetWindowRect`` raises
        # ``pywintypes.error`` for the dead HWND and the helper
        # converts that to ``None``. Drive this by spawning a real
        # window, capturing its HWND, destroying it, then asking for
        # geometry -- exactly the race the production handler exists
        # to absorb.
        try:
            root = tkinter.Tk()
        except tkinter.TclError as exc:
            pytest.skip(f"tkinter.Tk() failed at fixture time: {exc}")
        root.geometry("200x100+10+10")
        root.update_idletasks()
        root.update()
        hwnd = find_vrchat_hwnd(os.getpid())
        assert hwnd is not None
        try:
            root.destroy()

            assert get_window_rect(hwnd) is None
        finally:
            try:
                root.destroy()
            except tkinter.TclError:
                pass
