"""Tests for :mod:`vrcpilot.controls.guard`.

``ensure_target`` is the only safety check between user code and the
synthetic-input backends, so every branch is exercised. The autouse
``_no_real_vrchat`` fixture pins ``psutil.process_iter`` to empty by
default, which makes :func:`vrcpilot.process.resolve_pid` raise
:class:`VRChatNotRunningError`; each test that needs the "VRChat is
running" branch patches ``vrcpilot.controls.guard.resolve_pid`` directly
to return a fixed PID.

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
from vrcpilot.process import VRChatMultipleInstancesError, VRChatNotRunningError


class TestEnsureTarget:
    def test_raises_not_implemented_on_wayland_native(self, mocker: MockerFixture):
        # Wayland native sessions cannot satisfy is_foreground(), so
        # the focus loop would never converge. Surface a clear
        # NotImplementedError before any side effect.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=True)
        with pytest.raises(NotImplementedError, match="X11 or XWayland"):
            ensure_target()

    def test_raises_when_vrchat_not_running(self, mocker: MockerFixture):
        # Autouse _no_real_vrchat fixture already makes resolve_pid
        # raise VRChatNotRunningError, but patching it explicitly is
        # less coupled to the global fixture and matches the style of
        # the other branch tests.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch(
            "vrcpilot.controls.guard.resolve_pid",
            side_effect=VRChatNotRunningError("VRChat is not running"),
        )
        with pytest.raises(VRChatNotRunningError, match="not running"):
            ensure_target()

    def test_raises_multiple_instances_when_pid_omitted(self, mocker: MockerFixture):
        # resolve_pid surfaces VRChatMultipleInstancesError when multiple
        # VRChat processes are running and pid= is omitted. Guard must
        # propagate (not silently first-match).
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch(
            "vrcpilot.controls.guard.resolve_pid",
            side_effect=VRChatMultipleInstancesError([4242, 5151]),
        )
        with pytest.raises(VRChatMultipleInstancesError):
            ensure_target()

    def test_no_op_when_already_foreground_returns_pid(self, mocker: MockerFixture):
        # Happy path: VRChat is running and is_foreground() is True
        # on the first probe -- focus() must not be called at all.
        # ensure_target must return the resolved PID so callers can
        # reuse it without re-running resolve_pid.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch("vrcpilot.controls.guard.resolve_pid", return_value=4242)
        is_fg = mocker.patch(
            "vrcpilot.controls.guard.window.is_foreground", return_value=True
        )
        focus = mocker.patch("vrcpilot.controls.guard.window.focus")

        result = ensure_target()

        assert result == 4242
        is_fg.assert_called_once_with(pid=4242)
        focus.assert_not_called()

    def test_passes_pid_through_to_resolve_pid(self, mocker: MockerFixture):
        # Caller-supplied pid must flow through resolve_pid (which
        # short-circuits to that PID) and into window.is_foreground.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        resolve_spy = mocker.patch(
            "vrcpilot.controls.guard.resolve_pid", return_value=9999
        )
        is_fg = mocker.patch(
            "vrcpilot.controls.guard.window.is_foreground", return_value=True
        )

        result = ensure_target(pid=9999)

        assert result == 9999
        resolve_spy.assert_called_once_with(9999)
        is_fg.assert_called_once_with(pid=9999)

    def test_focuses_then_returns_when_focus_succeeds(self, mocker: MockerFixture):
        # First is_foreground() call drives the focus path; the second
        # confirms VRChat surfaced after the first focus() invocation.
        # Both is_foreground and focus must receive the resolved pid.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch("vrcpilot.controls.guard.resolve_pid", return_value=4242)
        is_fg = mocker.patch(
            "vrcpilot.controls.guard.window.is_foreground",
            side_effect=[False, True],
        )
        focus = mocker.patch("vrcpilot.controls.guard.window.focus", return_value=True)

        result = ensure_target()

        assert result == 4242
        assert is_fg.call_count == 2
        for call in is_fg.call_args_list:
            assert call.kwargs == {"pid": 4242}
        focus.assert_called_once_with(pid=4242)

    def test_retries_focus_until_window_surfaces(self, mocker: MockerFixture):
        # Some WMs (e.g. GNOME Mutter) silently drop the first
        # _NET_ACTIVE_WINDOW request as focus-stealing prevention. The
        # guard must call focus() again until the WM honors it rather
        # than failing on a single stale reading.
        mocker.patch("vrcpilot.controls.guard.is_wayland_native", return_value=False)
        mocker.patch("vrcpilot.controls.guard.resolve_pid", return_value=4242)
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
        mocker.patch("vrcpilot.controls.guard.resolve_pid", return_value=4242)
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
        mocker.patch("vrcpilot.controls.guard.resolve_pid", return_value=4242)
        mocker.patch("vrcpilot.controls.guard.window.is_foreground", return_value=False)
        mocker.patch("vrcpilot.controls.guard.window.focus", return_value=True)
        # Deadline (start + timeout) baked at iteration 0; iteration 1
        # sees a far-future "now" and trips the giveup branch.
        mocker.patch("vrcpilot.controls.guard.time.monotonic", side_effect=[0.0, 999.0])
        mocker.patch("vrcpilot.controls.guard.time.sleep")
        with pytest.raises(VRChatNotFocusedError, match="after focus"):
            ensure_target()
