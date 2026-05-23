"""Tests for :mod:`vrcpilot.geometry`.

The autouse fixture in :mod:`tests.conftest` forces
:func:`vrcpilot.process.find_pids` to return an empty list for every
test, so :func:`vrcpilot.process.resolve_pid` raises
:class:`VRChatNotRunningError` by default. The geometry helper catches
that and returns ``None``, making the "VRChat not running" path
testable on every host without a live VRChat or even a usable display.

Platform branches that *would* reach into Win32 / X11 are gated by the
helpers in :mod:`tests.helpers` so each runner only executes the path
relevant to its OS.
"""

from __future__ import annotations

import sys

import pytest
from pytest_mock import MockerFixture

from tests.helpers import only_linux, only_windows
from vrcpilot import geometry
from vrcpilot.geometry import get_vrchat_window_rect
from vrcpilot.process import VRChatMultipleInstancesError, VRChatNotRunningError


class TestGetVrchatWindowRect:
    """``resolve_pid()`` raises ``VRChatNotRunningError`` by default, helper
    must return ``None`` regardless of which platform branch is taken."""

    @only_windows
    def test_returns_none_when_vrchat_not_running_windows(self):
        # Win32 path: ``resolve_pid()`` raises ``VRChatNotRunningError``
        # (autouse fixture) -> caught and ``None`` is returned before
        # any Win32 API is touched.
        assert get_vrchat_window_rect() is None

    @only_linux
    def test_returns_none_when_vrchat_not_running_linux(self):
        # X11 path: ``resolve_pid()`` raises ``VRChatNotRunningError``
        # (autouse fixture) -> caught and ``None`` is returned before
        # opening a display, so this works even on hosts without an X
        # server.
        assert get_vrchat_window_rect() is None

    def test_returns_none_when_vrchat_not_running(self, mocker: MockerFixture) -> None:
        """``VRChatNotRunningError`` from ``resolve_pid`` is swallowed and
        ``None`` is returned.

        Backend helpers must not be invoked.
        """
        mocker.patch(
            "vrcpilot.geometry.process.resolve_pid",
            side_effect=VRChatNotRunningError("VRChat is not running"),
        )
        if sys.platform == "win32":
            backend_spy = mocker.spy(geometry, "_get_vrchat_rect_win32")
        elif sys.platform == "linux":
            backend_spy = mocker.spy(geometry, "_get_vrchat_rect_linux")
        else:
            backend_spy = None

        assert get_vrchat_window_rect() is None

        if backend_spy is not None:
            assert backend_spy.call_count == 0

    def test_raises_when_multiple_instances_and_no_pid(
        self, mocker: MockerFixture
    ) -> None:
        """``VRChatMultipleInstancesError`` is **not** swallowed; it propagates
        so CLI callers can prompt for ``--pid``."""
        mocker.patch(
            "vrcpilot.geometry.process.resolve_pid",
            side_effect=VRChatMultipleInstancesError([111, 222]),
        )
        with pytest.raises(VRChatMultipleInstancesError) as excinfo:
            get_vrchat_window_rect()
        assert excinfo.value.pids == [111, 222]

    def test_resolves_pid_when_omitted(self, mocker: MockerFixture) -> None:
        """When *pid* is omitted, ``process.resolve_pid(None)`` is called and
        its return value is forwarded to the platform backend."""
        resolve_mock = mocker.patch(
            "vrcpilot.geometry.process.resolve_pid", return_value=42
        )
        if sys.platform == "win32":
            backend_mock = mocker.patch(
                "vrcpilot.geometry._get_vrchat_rect_win32",
                return_value=(0, 0, 1280, 720),
            )
        elif sys.platform == "linux":
            backend_mock = mocker.patch(
                "vrcpilot.geometry._get_vrchat_rect_linux",
                return_value=(0, 0, 1280, 720),
            )
        else:
            pytest.skip("unsupported platform")

        rect = get_vrchat_window_rect()

        assert rect == (0, 0, 1280, 720)
        resolve_mock.assert_called_once_with(None)
        backend_mock.assert_called_once_with(pid=42)

    def test_passes_explicit_pid_to_backend(self, mocker: MockerFixture) -> None:
        """When *pid* is given explicitly, it is forwarded through
        ``resolve_pid`` (which returns it unchanged) to the backend."""
        resolve_mock = mocker.patch(
            "vrcpilot.geometry.process.resolve_pid", return_value=12345
        )
        if sys.platform == "win32":
            backend_mock = mocker.patch(
                "vrcpilot.geometry._get_vrchat_rect_win32",
                return_value=(10, 20, 1920, 1080),
            )
        elif sys.platform == "linux":
            backend_mock = mocker.patch(
                "vrcpilot.geometry._get_vrchat_rect_linux",
                return_value=(10, 20, 1920, 1080),
            )
        else:
            pytest.skip("unsupported platform")

        rect = get_vrchat_window_rect(pid=12345)

        assert rect == (10, 20, 1920, 1080)
        resolve_mock.assert_called_once_with(12345)
        backend_mock.assert_called_once_with(pid=12345)


class TestPlatformBackends:
    """Direct tests for the private platform helpers."""

    @only_windows
    def test_win32_backend_returns_none_when_hwnd_missing(
        self, mocker: MockerFixture
    ) -> None:
        from vrcpilot import geometry as geometry_mod

        mocker.patch("vrcpilot.windows.find_vrchat_hwnd", return_value=None)
        assert geometry_mod._get_vrchat_rect_win32(pid=12345) is None  # pyright: ignore[reportPrivateUsage]

    @only_windows
    def test_win32_backend_passes_pid_to_find_vrchat_hwnd(
        self, mocker: MockerFixture
    ) -> None:
        from vrcpilot import geometry as geometry_mod

        find_hwnd_mock = mocker.patch(
            "vrcpilot.windows.find_vrchat_hwnd", return_value=0xCAFE
        )
        get_rect_mock = mocker.patch(
            "vrcpilot.windows.get_window_rect", return_value=(0, 0, 800, 600)
        )

        rect = geometry_mod._get_vrchat_rect_win32(pid=12345)  # pyright: ignore[reportPrivateUsage]

        assert rect == (0, 0, 800, 600)
        find_hwnd_mock.assert_called_once_with(12345)
        get_rect_mock.assert_called_once_with(0xCAFE)

    @only_linux
    def test_x11_backend_returns_none_when_display_unavailable(
        self, mocker: MockerFixture
    ) -> None:
        from vrcpilot import geometry as geometry_mod

        mocker.patch("vrcpilot.linux.open_x11_display", return_value=None)
        assert geometry_mod._get_vrchat_rect_linux(pid=12345) is None  # pyright: ignore[reportPrivateUsage]

    @only_linux
    def test_x11_backend_passes_pid_to_find_vrchat_window(
        self, mocker: MockerFixture
    ) -> None:
        from vrcpilot import geometry as geometry_mod

        fake_display = mocker.MagicMock()
        mocker.patch("vrcpilot.linux.open_x11_display", return_value=fake_display)
        find_window_mock = mocker.patch(
            "vrcpilot.linux.find_vrchat_window", return_value=None
        )

        result = geometry_mod._get_vrchat_rect_linux(pid=12345)  # pyright: ignore[reportPrivateUsage]

        assert result is None
        find_window_mock.assert_called_once_with(fake_display, 12345)
        fake_display.close.assert_called_once_with()
