"""Cross-platform behaviour tests for :class:`vrcpilot.capture.Capture`.

Only the parts of :class:`Capture` that run *before* platform dispatch
are exercised here: argument validation and the delegation to
:func:`vrcpilot.process.resolve_pid`. Once dispatch reaches
``_select_capture_backend`` the behaviour is platform-specific and is
covered by the integration-real modules ``test_linux.py`` /
``test_windows.py``.

The PID resolution contract is verified by driving the *real*
``resolve_pid`` against the project-wide autouse fixture
(:func:`tests.conftest._no_real_vrchat`) which keeps ``process_iter``
empty. In that state ``Capture()`` (pid omitted) must surface
``VRChatNotRunningError`` *before* any platform-specific backend code
runs, which proves that resolution happens up front in the public
``Capture`` surface.
"""

from __future__ import annotations

import pytest

from vrcpilot.capture import Capture
from vrcpilot.process import VRChatNotRunningError


class TestCaptureArgumentValidation:
    """``__init__`` argument validation (no backend ever opened)."""

    @pytest.mark.parametrize("frame_timeout", [0.0, -0.1, -1.0])
    def test_non_positive_frame_timeout_raises_value_error(self, frame_timeout: float):
        # Spec: a non-positive timeout would either spin or raise on
        # every read; we surface the misuse at construction time so the
        # traceback points at the caller, not at the first read().
        with pytest.raises(ValueError, match="frame_timeout must be > 0"):
            Capture(frame_timeout=frame_timeout)


class TestCapturePidResolution:
    """Capture must consult :func:`resolve_pid` before opening a backend.

    The project-wide autouse fixture (``_no_real_vrchat``) replaces
    ``psutil.process_iter`` with an empty iterator, so the real
    ``resolve_pid`` reports "no VRChat" and short-circuits the dispatch
    to platform backends — which is precisely the observable proof that
    resolution runs first.
    """

    def test_missing_pid_raises_vrchat_not_running(self):
        # Spec: omitting ``pid`` consults ``resolve_pid(None)``; with no
        # VRChat running the resolver raises ``VRChatNotRunningError``
        # and the platform-specific backend is never reached. This is
        # the same error users see from a direct ``resolve_pid`` call.
        with pytest.raises(VRChatNotRunningError, match="VRChat is not running"):
            Capture()
