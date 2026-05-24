"""Tests for :mod:`vrcpilot.controls.guard`.

The guard's behaviour decomposes into three observable surfaces:

1. **VRChat not running** — surfaces ``VRChatNotRunningError`` from
   :func:`vrcpilot.process.resolve_pid`. Verified end-to-end via the
   project-wide autouse ``_no_real_vrchat`` fixture (which pins
   ``psutil.process_iter`` to empty for every test), so no further
   mocking is needed here.
2. **Wayland-native session** — ``ensure_target`` raises
   :class:`NotImplementedError` because the focus retry loop would
   never converge. Verified only when an actual Wayland session is
   active; on X11 hosts the assertion would require mocking
   :func:`vrcpilot.session.is_wayland_native`, which is one of
   vrcpilot's own internal functions and therefore off-limits.
3. **Successful focus** (no-op + retry loop) — requires a real X11
   display **and** a real focusable window the guard can drive via
   ``window.is_foreground`` / ``window.focus``. That is out of scope
   for unit tests: it is covered by ``tests/e2e/focus_unfocus.py``,
   which exercises the same code paths against a live VRChat window.
"""

from __future__ import annotations

import pytest

from vrcpilot.controls.guard import ensure_target
from vrcpilot.process import VRChatNotRunningError
from vrcpilot.session import is_wayland_native


class TestEnsureTargetNoVrchat:
    """``ensure_target`` must surface VRChat-not-running cleanly.

    The autouse ``_no_real_vrchat`` fixture pins
    :func:`vrcpilot.process.find_pids` to empty, so
    :func:`vrcpilot.process.resolve_pid` raises
    :class:`VRChatNotRunningError` -- the guard must propagate that
    instead of returning a sentinel or hanging.

    Skipped on Wayland-native sessions because the Wayland branch fires
    first and obscures the not-running path.
    """

    def test_raises_vrchat_not_running_error(self) -> None:
        if is_wayland_native():
            pytest.skip("Wayland-native session short-circuits before resolve_pid")
        with pytest.raises(VRChatNotRunningError, match="not running"):
            ensure_target()


class TestEnsureTargetWaylandNative:
    """``ensure_target`` must reject Wayland-native sessions immediately.

    Skipped on every host that is not Wayland-native: the only way to
    exercise this branch without mocking vrcpilot's own
    :func:`is_wayland_native` is to actually be on Wayland. The branch
    itself is small (a single ``raise``) so e2e on a Wayland session
    can confirm it if needed.
    """

    def test_raises_not_implemented_error(self) -> None:
        if not is_wayland_native():
            pytest.skip("Wayland-native session required to exercise this branch")
        with pytest.raises(NotImplementedError, match="X11 or XWayland"):
            ensure_target()
