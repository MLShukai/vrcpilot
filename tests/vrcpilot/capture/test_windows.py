"""Integration-real tests for :mod:`vrcpilot.capture.windows`.

The module is Windows-only at import time (it raises ``ImportError`` on
other platforms because it depends on ``windows_capture``), so the
whole file is guarded by a module-level skip before any production
import runs.

These tests exercise the real backend code against the real
``windows_capture`` library. They do *not* mock that library — the
test strategy disallows third-party surface mocking, and the previous
fakes-based tests that did so were removed in this refactor.

What is covered here:

- ``find_vrchat_hwnd`` returning ``None`` for a non-existent PID — the
  test fakes the *PID*, not the WGC entry point. This is the only fail
  path reachable from a real Windows runner without a real VRChat
  instance.

What is *not* covered here (deferred to e2e):

- Successful frame capture from a real VRChat window.
- WGC start failure on hosts without the right OS/GPU support.
- Frame decoding (BGRA -> RGB), latest-only buffer semantics, and the
  ``read`` timeout — all require a live WGC session producing frames.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only module", allow_module_level=True)

from vrcpilot.capture.windows import Win32CaptureBackend  # noqa: E402

# A PID that cannot plausibly correspond to a running VRChat process.
# ``find_vrchat_hwnd`` walks the top-level window list and matches
# GetWindowThreadProcessId; an unused PID yields no match and the
# backend's "window is not yet mapped" branch fires.
_NONEXISTENT_PID = 99_999_999


class TestWin32CaptureBackendAgainstRealLibrary:
    """Real ``windows_capture``, no VRChat process — only the not-mapped path
    runs."""

    def test_raises_when_vrchat_window_is_not_mapped(self):
        # Spec: when ``find_vrchat_hwnd`` returns ``None`` (no top-level
        # window owned by the given PID exists), the backend must raise
        # ``RuntimeError`` so the caller sees a single typed failure for
        # "VRChat not visible yet" — never reaching the WGC session
        # which would crash on a null HWND.
        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            Win32CaptureBackend(frame_timeout=1.0, pid=_NONEXISTENT_PID)
