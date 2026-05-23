"""Tests for :mod:`vrcpilot.window` (top-level platform dispatch).

The dispatch raises ``NotImplementedError`` for platforms other than
Windows or Linux. We intentionally do NOT exercise that branch by
patching ``sys.platform`` — the real interpreter only ever runs on one
platform at a time, and the unsupported branch cannot reasonably be
hit in production. What this file verifies is that on the *current*
platform, ``focus()`` / ``is_foreground()`` / ``unfocus()``:

* resolve ``pid`` via :func:`vrcpilot.process.resolve_pid` when omitted,
* forward an explicit ``pid=`` to the backend unchanged,
* return ``False`` when VRChat is not running (existing contract), and
* re-raise :class:`VRChatMultipleInstancesError` when multiple instances
  are running and the caller did not disambiguate.
"""

from __future__ import annotations

import sys
import warnings

import pytest
from pytest_mock import MockerFixture

import vrcpilot.window
from vrcpilot.process import VRChatMultipleInstancesError


def _backend_module_name() -> str:
    if sys.platform == "win32":
        return "vrcpilot.window.windows"
    return "vrcpilot.window.linux"


def _backend_focus_name() -> str:
    return f"{_backend_module_name()}.focus_window"


def _backend_is_foreground_name() -> str:
    return f"{_backend_module_name()}.is_window_foreground"


def _backend_unfocus_name() -> str:
    return f"{_backend_module_name()}.unfocus_window"


@pytest.fixture(autouse=True)
def _require_supported_platform():
    if sys.platform not in ("win32", "linux"):
        pytest.skip("dispatch only wired for Windows and Linux")


class TestPublicSurface:
    def test_module_exposes_focus_and_unfocus(self):
        # The package re-exports these via ``vrcpilot.__all__``; the
        # window module itself must keep them as the canonical entry
        # points so the dispatch layer cannot be silently removed.
        assert callable(vrcpilot.window.focus)
        assert callable(vrcpilot.window.unfocus)
        assert callable(vrcpilot.window.is_foreground)


class TestFocus:
    def test_returns_false_when_vrchat_not_running(self):
        # Autouse ``_no_real_vrchat`` (tests/conftest.py) leaves
        # ``find_pids()`` empty, so ``resolve_pid(None)`` raises
        # ``VRChatNotRunningError``. The dispatch must catch that and
        # return ``False`` rather than propagate.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert vrcpilot.window.focus() is False

    def test_passes_explicit_pid_to_backend(self, mocker: MockerFixture):
        backend = mocker.patch(_backend_focus_name(), return_value=True)

        assert vrcpilot.window.focus(pid=12345) is True
        backend.assert_called_once_with(pid=12345)

    def test_resolves_pid_when_omitted(self, mocker: MockerFixture):
        # Single running instance: ``resolve_pid(None)`` returns it and
        # the dispatch forwards the resolved value to the backend.
        mocker.patch("vrcpilot.process.pid.find_pids", return_value=[7777])
        backend = mocker.patch(_backend_focus_name(), return_value=True)

        assert vrcpilot.window.focus() is True
        backend.assert_called_once_with(pid=7777)

    def test_raises_when_multiple_instances_and_no_pid(self, mocker: MockerFixture):
        # Two running instances + no ``pid=`` => CLI users need a hint
        # to disambiguate, so the error propagates.
        mocker.patch("vrcpilot.process.pid.find_pids", return_value=[1, 2])
        backend = mocker.patch(_backend_focus_name(), return_value=True)

        with pytest.raises(VRChatMultipleInstancesError):
            vrcpilot.window.focus()
        backend.assert_not_called()


class TestIsForeground:
    def test_returns_false_when_vrchat_not_running(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert vrcpilot.window.is_foreground() is False

    def test_passes_explicit_pid_to_backend(self, mocker: MockerFixture):
        backend = mocker.patch(_backend_is_foreground_name(), return_value=True)

        assert vrcpilot.window.is_foreground(pid=12345) is True
        backend.assert_called_once_with(pid=12345)

    def test_resolves_pid_when_omitted(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.process.pid.find_pids", return_value=[7777])
        backend = mocker.patch(_backend_is_foreground_name(), return_value=False)

        assert vrcpilot.window.is_foreground() is False
        backend.assert_called_once_with(pid=7777)

    def test_raises_when_multiple_instances_and_no_pid(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.process.pid.find_pids", return_value=[1, 2])
        backend = mocker.patch(_backend_is_foreground_name(), return_value=False)

        with pytest.raises(VRChatMultipleInstancesError):
            vrcpilot.window.is_foreground()
        backend.assert_not_called()


class TestUnfocus:
    def test_returns_false_when_vrchat_not_running(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            assert vrcpilot.window.unfocus() is False

    def test_passes_explicit_pid_to_backend(self, mocker: MockerFixture):
        backend = mocker.patch(_backend_unfocus_name(), return_value=True)

        assert vrcpilot.window.unfocus(pid=12345) is True
        backend.assert_called_once_with(pid=12345)

    def test_resolves_pid_when_omitted(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.process.pid.find_pids", return_value=[7777])
        backend = mocker.patch(_backend_unfocus_name(), return_value=True)

        assert vrcpilot.window.unfocus() is True
        backend.assert_called_once_with(pid=7777)

    def test_raises_when_multiple_instances_and_no_pid(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.process.pid.find_pids", return_value=[1, 2])
        backend = mocker.patch(_backend_unfocus_name(), return_value=True)

        with pytest.raises(VRChatMultipleInstancesError):
            vrcpilot.window.unfocus()
        backend.assert_not_called()
