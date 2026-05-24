"""Integration-real tests for :mod:`vrcpilot.capture.linux`.

The module is Linux-only at import time (it raises ``ImportError`` on
other platforms because it depends on ``Xlib``), so the whole file is
guarded by a module-level skip before any production import runs.

These tests exercise the real backend code against a real X server.
They do *not* mock ``Xlib`` symbols — the test strategy disallows
third-party surface mocking, and the previous fakes-based tests that
did so were removed in this refactor.

What is covered here:

- ``is_wayland_native()`` short-circuit (env-only, no X server needed).
- ``find_vrchat_window`` against a real display returning ``None`` when
  no VRChat process is running — the test fakes the *PID*, not the X
  server. This is the only fail path reachable from a real X display
  without a real VRChat instance.

What is *not* covered here (deferred to e2e):

- Successful frame capture from a real VRChat window.
- Composite-extension-missing / redirect-failed paths (require a
  specially configured X server).
- ``get_image`` XError paths (require provoking real X errors).
- ``read`` on a resized-to-zero window.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "linux":
    pytest.skip("Linux-only module", allow_module_level=True)

from tests.helpers import requires_x11_display  # noqa: E402
from vrcpilot.capture.linux import X11CaptureBackend  # noqa: E402

# A PID that cannot plausibly correspond to a running process. ``find_vrchat_window``
# walks _NET_CLIENT_LIST and matches _NET_WM_PID; an unused PID yields no match
# and the backend's "window is not yet mapped" branch fires.
_NONEXISTENT_PID = 99_999_999


class TestX11CaptureBackendWaylandGuard:
    """The Wayland-native guard is env-only and runs on any Linux host."""

    def test_wayland_native_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch):
        # Spec: continuous capture has no fallback on native Wayland
        # (XWayland sessions are fine because they expose DISPLAY).
        # We must fail fast at construction time rather than open a
        # broken X connection.
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("DISPLAY", raising=False)

        with pytest.raises(RuntimeError, match="native Wayland is not supported"):
            X11CaptureBackend(pid=_NONEXISTENT_PID)


@requires_x11_display
class TestX11CaptureBackendAgainstRealDisplay:
    """Real X server, no VRChat process — only the not-mapped path runs."""

    def test_raises_when_vrchat_window_is_not_mapped(self):
        # Spec: when ``find_vrchat_window`` returns ``None`` (no window
        # owned by the given PID exists in _NET_CLIENT_LIST), the
        # backend must raise ``RuntimeError`` so the caller sees a
        # single typed failure for "VRChat not visible yet".
        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            X11CaptureBackend(pid=_NONEXISTENT_PID)
