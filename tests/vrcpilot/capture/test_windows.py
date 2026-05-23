"""Tests for :mod:`vrcpilot.capture.windows`.

The module raises ``ImportError`` on non-Windows because it depends on
``windows_capture``, so a module-level skip up front gates the rest of
the file. ``Win32CaptureBackend`` now takes ``pid`` as a required
keyword argument (PID resolution lives one layer up in
:class:`vrcpilot.capture.Capture`), so each test passes a concrete PID
explicitly. The WGC failure path is covered by replacing
``WindowsCapture`` with :class:`tests.fakes.FakeWindowsCapture` and
toggling its ``start_raises`` attribute.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only module", allow_module_level=True)

from pytest_mock import MockerFixture

from tests.fakes import make_fresh_windows_capture_subclass
from vrcpilot.capture.windows import Win32CaptureBackend


@pytest.fixture
def win32_hwnd(mocker: MockerFixture) -> None:
    """Patch ``find_vrchat_hwnd`` to a happy-path HWND.

    The backend now receives ``pid`` from the caller; tests that need
    to exercise the post-lookup branches use this fixture to short-
    circuit the HWND search with a concrete value.
    """
    mocker.patch("vrcpilot.capture.windows.find_vrchat_hwnd", return_value=12345)


class TestWin32CaptureBackend:
    def test_raises_when_hwnd_missing(self, mocker: MockerFixture):
        # The caller passed a valid PID but the top-level HWND is not
        # yet mapped — raise rather than fall through to
        # ``WindowsCapture``, which would crash on a null HWND.
        mocker.patch("vrcpilot.capture.windows.find_vrchat_hwnd", return_value=None)

        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            Win32CaptureBackend(frame_timeout=1.0, pid=4242)

    def test_pid_is_forwarded_to_find_vrchat_hwnd(self, mocker: MockerFixture):
        # The backend must thread the caller-provided PID into
        # ``find_vrchat_hwnd`` — otherwise the multi-instance contract
        # one layer up cannot guarantee the right window is captured.
        find_hwnd = mocker.patch(
            "vrcpilot.capture.windows.find_vrchat_hwnd", return_value=None
        )
        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            Win32CaptureBackend(frame_timeout=1.0, pid=98765)
        find_hwnd.assert_called_once_with(98765)

    def test_wraps_oserror_at_start(self, mocker: MockerFixture, win32_hwnd: None):
        # WGC start can raise ``OSError`` on hosts without GPU support
        # for Windows.Graphics.Capture. The backend must wrap as
        # ``RuntimeError`` so callers see one error type, while keeping
        # the original on ``__cause__`` for diagnosis.
        del win32_hwnd

        fresh = make_fresh_windows_capture_subclass()
        original = OSError("WGC unavailable")
        fresh.start_raises = original
        mocker.patch("vrcpilot.capture.windows.WindowsCapture", fresh)

        with pytest.raises(RuntimeError, match="Failed to start WGC session") as ei:
            Win32CaptureBackend(frame_timeout=1.0, pid=4242)
        assert ei.value.__cause__ is original
