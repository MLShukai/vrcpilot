"""Tests for :mod:`vrcpilot.controls.guard`.

``ensure_target`` is the only safety check between user code and the
synthetic-input backends, so every branch is exercised. The autouse
``_no_real_vrchat`` fixture pins ``find_pid()`` to ``None`` by default;
each test that needs the "VRChat is running" branch overrides the
``vrcpilot.controls.guard.find_pid`` symbol the module imported.

``vrcpilot.window`` functions are patched via attribute access on the
guard module (the implementation does ``from vrcpilot import window``)
rather than at their canonical paths -- patching via the bound name is
the only way to intercept calls the module already resolved at import
time.
"""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from vrcpilot.controls.errors import VRChatNotFocusedError
from vrcpilot.controls.guard import ensure_target
from vrcpilot.process import VRChatNotRunningError


class TestEnsureTarget:
    def test_raises_not_implemented_on_wayland_native(self, mocker: MockerFixture):
        # Wayland native sessions cannot satisfy is_foreground(), so
        # the focus loop would never converge. Surface a clear
        # NotImplementedError before any side effect.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=True)
        with pytest.raises(NotImplementedError, match="X11 or XWayland"):
            ensure_target()

    def test_raises_when_vrchat_not_running(self, mocker: MockerFixture):
        # Autouse _no_real_vrchat fixture already pins find_pid to
        # None, but patching the local import is explicit and lets the
        # other branch tests override it without ambiguity.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch("vrcpilot.controls.guard.find_pid", return_value=None)
        with pytest.raises(VRChatNotRunningError, match="not running"):
            ensure_target()

    def test_no_op_when_already_foreground(self, mocker: MockerFixture):
        # Happy path: VRChat is running and is_foreground() is True
        # on the first probe -- focus() must not be called at all.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch("vrcpilot.controls.guard.find_pid", return_value=4242)
        is_fg = mocker.patch(
            "vrcpilot.controls.guard.window.is_foreground", return_value=True
        )
        focus = mocker.patch("vrcpilot.controls.guard.window.focus")

        ensure_target()  # no exception expected

        is_fg.assert_called_once()
        focus.assert_not_called()

    def test_focuses_then_returns_when_focus_succeeds(self, mocker: MockerFixture):
        # First is_foreground() call drives the focus path; the second
        # confirms VRChat surfaced after the first focus() invocation.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch("vrcpilot.controls.guard.find_pid", return_value=4242)
        is_fg = mocker.patch(
            "vrcpilot.controls.guard.window.is_foreground",
            side_effect=[False, True],
        )
        focus = mocker.patch("vrcpilot.controls.guard.window.focus", return_value=True)

        ensure_target()  # no exception expected

        assert is_fg.call_count == 2
        focus.assert_called_once()

    def test_retries_focus_until_window_surfaces(self, mocker: MockerFixture):
        # Some WMs (e.g. GNOME Mutter) silently drop the first
        # _NET_ACTIVE_WINDOW request as focus-stealing prevention. The
        # guard must call focus() again until the WM honors it rather
        # than failing on a single stale reading.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch("vrcpilot.controls.guard.find_pid", return_value=4242)
        is_fg = mocker.patch(
            "vrcpilot.controls.guard.window.is_foreground",
            side_effect=[False, False, False, True],
        )
        focus = mocker.patch("vrcpilot.controls.guard.window.focus", return_value=True)
        sleep = mocker.patch("vrcpilot.controls.guard.time.sleep")

        ensure_target()  # no exception expected

        # is_foreground: 1 prefix probe + 3 inside the retry loop.
        assert is_fg.call_count == 4
        # focus: every loop iteration calls focus() before re-probing,
        # so 3 attempts (matching the 3 inside-loop is_foreground probes).
        assert focus.call_count == 3
        # 2 sleeps between the 3 inside-loop iterations.
        assert sleep.call_count == 2

    def test_raises_when_focus_returns_false(self, mocker: MockerFixture):
        # Native call to bring the window forward failed (e.g. another
        # app stole foreground or X11 returned an XError) -- the guard
        # must propagate as VRChatNotFocusedError without retrying.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch("vrcpilot.controls.guard.find_pid", return_value=4242)
        mocker.patch("vrcpilot.controls.guard.window.is_foreground", return_value=False)
        mocker.patch("vrcpilot.controls.guard.window.focus", return_value=False)
        with pytest.raises(VRChatNotFocusedError, match=r"focus\(\) failed"):
            ensure_target()

    def test_raises_when_still_not_foreground_after_focus(self, mocker: MockerFixture):
        # focus() keeps reporting success but the window never surfaces
        # even after the retry window expired. Guard must not silently
        # continue. The time.monotonic patch makes the loop give up
        # after a single iteration so the test stays fast.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch("vrcpilot.controls.guard.find_pid", return_value=4242)
        mocker.patch("vrcpilot.controls.guard.window.is_foreground", return_value=False)
        mocker.patch("vrcpilot.controls.guard.window.focus", return_value=True)
        # Deadline (start + timeout) baked at iteration 0; iteration 1
        # sees a far-future "now" and trips the giveup branch.
        mocker.patch("vrcpilot.controls.guard.time.monotonic", side_effect=[0.0, 999.0])
        mocker.patch("vrcpilot.controls.guard.time.sleep")
        with pytest.raises(VRChatNotFocusedError, match="after focus"):
            ensure_target()
