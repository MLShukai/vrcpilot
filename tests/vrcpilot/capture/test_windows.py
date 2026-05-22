"""Tests for :mod:`vrcpilot.capture.windows`.

The module raises ``ImportError`` on non-Windows because it depends on
``windows_capture``, so a module-level skip up front gates the rest of
the file. Below the gate, the autouse ``_no_real_vrchat`` fixture in
:mod:`tests.conftest` pins ``find_pid()`` to ``None`` so the
"VRChat not running" branch is exercised with zero explicit mocks. The
WGC failure path is covered by replacing ``WindowsCapture`` with
:class:`tests.fakes.FakeWindowsCapture` and toggling its
``start_raises`` attribute.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only module", allow_module_level=True)

from pytest_mock import MockerFixture

from tests.fakes import FakeWindowsCapture, make_fresh_windows_capture_subclass
from vrcpilot.capture.windows import Win32CaptureBackend


@pytest.fixture
def win32_pid_and_hwnd(mocker: MockerFixture) -> None:
    """Patch ``find_pid`` / ``find_vrchat_hwnd`` to a happy-path PID and HWND.

    The autouse fixture in :mod:`tests.conftest` pins ``find_pid``
    to ``None``; tests that need to exercise downstream branches use
    this fixture to override that default.
    """
    mocker.patch("vrcpilot.capture.windows.find_pid", return_value=4242)
    mocker.patch("vrcpilot.capture.windows.find_vrchat_hwnd", return_value=12345)


class TestWin32CaptureBackend:
    def test_raises_when_vrchat_not_running(self):
        # Autouse fixture pins ``find_pid()`` to ``None``; the backend
        # must surface this as RuntimeError before opening any WGC
        # session resources.
        with pytest.raises(RuntimeError, match="VRChat is not running"):
            Win32CaptureBackend(frame_timeout=1.0)

    def test_raises_when_hwnd_missing(self, mocker: MockerFixture):
        # ``find_pid`` succeeds but the top-level HWND is not yet
        # mapped — raise rather than fall through to ``WindowsCapture``,
        # which would crash on a null HWND.
        mocker.patch("vrcpilot.capture.windows.find_pid", return_value=4242)
        mocker.patch("vrcpilot.capture.windows.find_vrchat_hwnd", return_value=None)

        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            Win32CaptureBackend(frame_timeout=1.0)

    def test_wraps_oserror_at_start(
        self, mocker: MockerFixture, win32_pid_and_hwnd: None
    ):
        # WGC start can raise ``OSError`` on hosts without GPU support
        # for Windows.Graphics.Capture. The backend must wrap as
        # ``RuntimeError`` so callers see one error type, while keeping
        # the original on ``__cause__`` for diagnosis.
        del win32_pid_and_hwnd

        fresh = make_fresh_windows_capture_subclass()
        original = OSError("WGC unavailable")
        fresh.start_raises = original
        mocker.patch("vrcpilot.capture.windows.WindowsCapture", fresh)

        with pytest.raises(RuntimeError, match="Failed to start WGC session") as ei:
            Win32CaptureBackend(frame_timeout=1.0)
        assert ei.value.__cause__ is original
