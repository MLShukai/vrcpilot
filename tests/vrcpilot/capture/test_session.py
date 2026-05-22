"""Tests for :class:`vrcpilot.capture.Capture`.

Two backends, two test classes:

- :class:`TestCaptureWin32` runs only on Windows. Win32 deps
  (``windows_capture``) load on import there, so the tests substitute
  the WGC entry point with :class:`tests.fakes.FakeWindowsCapture`
  and drive frames synchronously.
- :class:`TestCaptureX11` runs only on Linux. The X11 backend module
  raises ``ImportError`` on non-Linux, so the class is gated with
  ``pytestmark = only_linux``. Real ``Xlib`` functions are patched
  with :class:`tests.fakes.FakeXDisplay` / :class:`tests.fakes.FakeXWindow`
  / :class:`tests.fakes.FakePixmap`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from pytest_mock import MockerFixture

from tests.fakes import (
    FakePixmap,
    FakeWindowsCapture,
    FakeXDisplay,
    FakeXGeometry,
    FakeXWindow,
    make_fresh_windows_capture_subclass,
    make_xerror_subclass,
)
from tests.helpers import only_linux, only_windows
from vrcpilot.capture import Capture

# ---------------------------------------------------------------------------
# Argument validation (cross-platform)
# ---------------------------------------------------------------------------


class TestCaptureValidation:
    """Argument validation that runs on every platform.

    These do not exercise a backend — construction fails at the
    parameter check before the platform dispatch, so they are safe
    regardless of OS.
    """

    @pytest.mark.parametrize("frame_timeout", [0.0, -0.1, -1.0])
    def test_rejects_non_positive_frame_timeout(self, frame_timeout: float):
        # Zero or negative timeouts would either spin or raise on every
        # ``read`` call; we surface the misuse at construction time so
        # the failure points at the caller, not at the first ``read``.
        with pytest.raises(ValueError, match="frame_timeout must be > 0"):
            Capture(frame_timeout=frame_timeout)


# ---------------------------------------------------------------------------
# Win32 backend
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_windows_capture(
    mocker: MockerFixture,
) -> type[FakeWindowsCapture]:
    """Patch ``WindowsCapture`` in the Win32 backend module with a fresh fake.

    Delegates the per-test subclass dance to
    :func:`tests.fakes.make_fresh_windows_capture_subclass` so
    isolation logic stays in the canonical fake module, not duplicated
    across test files.
    """
    fresh = make_fresh_windows_capture_subclass()
    mocker.patch("vrcpilot.capture.windows.WindowsCapture", fresh)
    return fresh


@pytest.fixture
def win32_pid_and_hwnd(mocker: MockerFixture) -> None:
    """Patch ``find_pid`` / ``find_vrchat_hwnd`` to a happy-path PID and HWND.

    Win32 tests overwhelmingly want the same canned values; pulling
    them into a fixture trims a pair of ``mocker.patch`` calls from
    every test body.
    """
    mocker.patch("vrcpilot.capture.windows.find_pid", return_value=4242)
    mocker.patch("vrcpilot.capture.windows.find_vrchat_hwnd", return_value=12345)


class TestCaptureWin32:
    """Win32 / WGC backend behaviour."""

    pytestmark = only_windows

    def test_lifecycle_returns_rgb_frame(
        self,
        win32_pid_and_hwnd: None,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        # Construct the WGC backend, emit a recognisable BGRA payload,
        # and verify Capture decodes a contiguous (H, W, 3) RGB array.
        del win32_pid_and_hwnd

        # 4 BGRA pixels: B=0x10 G=0x20 R=0x30 A=0xff -- after BGRA -> RGB
        # the first three channels per pixel should be (0x30, 0x20, 0x10).
        payload = b"\x10\x20\x30\xff" * (2 * 2)

        with Capture(frame_timeout=1.0) as cap:
            instance = fake_windows_capture.last_instance
            assert instance is not None
            instance.emit_frame(payload, 2, 2)

            frame = cap.read()

        assert isinstance(frame, np.ndarray)
        assert frame.shape == (2, 2, 3)
        assert frame.dtype == np.uint8
        assert frame.flags["C_CONTIGUOUS"]
        assert tuple(frame[0, 0].tolist()) == (0x30, 0x20, 0x10)

    def test_read_returns_latest_frame_only(
        self,
        win32_pid_and_hwnd: None,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        # Emit two frames back-to-back without an intervening read; the
        # latest-only buffer should drop the first and surface only the
        # most recent. Otherwise consumers fall behind by accumulating
        # FIFO lag -- the explicit anti-pattern this design rejects.
        del win32_pid_and_hwnd

        a_payload = b"\x00\x00\x00\xff" * 4  # all black -> RGB (0,0,0)
        b_payload = b"\x10\x20\x30\xff" * 4  # -> RGB (0x30,0x20,0x10)

        with Capture(frame_timeout=1.0) as cap:
            instance = fake_windows_capture.last_instance
            assert instance is not None
            instance.emit_frame(a_payload, 2, 2)
            instance.emit_frame(b_payload, 2, 2)

            frame = cap.read()

        assert tuple(frame[0, 0].tolist()) == (0x30, 0x20, 0x10)

    def test_read_times_out_when_no_frame(
        self,
        win32_pid_and_hwnd: None,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        # When the WGC session never delivers a frame, ``read`` must
        # raise ``TimeoutError`` rather than hang indefinitely.
        del win32_pid_and_hwnd, fake_windows_capture

        with Capture(frame_timeout=0.05) as cap:
            with pytest.raises(TimeoutError, match="No frame arrived"):
                cap.read()

    def test_init_raises_when_vrchat_not_running(
        self,
        mocker: MockerFixture,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        del fake_windows_capture
        mocker.patch("vrcpilot.capture.windows.find_pid", return_value=None)

        with pytest.raises(RuntimeError, match="VRChat is not running"):
            Capture()

    def test_init_raises_when_hwnd_missing(
        self,
        mocker: MockerFixture,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        del fake_windows_capture
        mocker.patch("vrcpilot.capture.windows.find_pid", return_value=4242)
        mocker.patch("vrcpilot.capture.windows.find_vrchat_hwnd", return_value=None)

        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            Capture()

    def test_init_wraps_oserror_at_start(
        self,
        win32_pid_and_hwnd: None,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        # WGC start can fail with OSError on machines without the right
        # GPU / OS support. Capture must re-raise as RuntimeError so the
        # caller sees a single failure mode, with the original OSError
        # preserved on ``__cause__`` for diagnosis.
        del win32_pid_and_hwnd
        original = OSError("WGC unavailable")
        fake_windows_capture.start_raises = original

        with pytest.raises(RuntimeError, match="Failed to start WGC session") as ei:
            Capture()
        assert ei.value.__cause__ is original

    def test_passes_expected_kwargs_to_windows_capture(
        self,
        mocker: MockerFixture,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        # Capture must turn off the cursor overlay and the WGC border so
        # the returned frame contains only window content, not OS chrome.
        # ``window_hwnd`` pins the target so the wrong window cannot be
        # captured if a same-titled one appears later.
        mocker.patch("vrcpilot.capture.windows.find_pid", return_value=4242)
        mocker.patch("vrcpilot.capture.windows.find_vrchat_hwnd", return_value=98765)

        cap = Capture()
        try:
            assert fake_windows_capture.last_kwargs == {
                "cursor_capture": False,
                "draw_border": False,
                "window_hwnd": 98765,
            }
        finally:
            cap.close()

    def test_close_is_idempotent(
        self,
        win32_pid_and_hwnd: None,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        # ``close`` may be called from ``__exit__``, by an explicit
        # caller, or from a finally block -- doubling up must be safe.
        del win32_pid_and_hwnd

        cap = Capture()
        cap.close()
        cap.close()
        cap.close()

        # Second/third calls are no-ops, so stop() is invoked exactly
        # once on the underlying CaptureControl.
        instance = fake_windows_capture.last_instance
        assert instance is not None
        assert instance.control.stop_calls == 1

    def test_read_after_close_raises(
        self,
        win32_pid_and_hwnd: None,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        del win32_pid_and_hwnd, fake_windows_capture

        cap = Capture()
        cap.close()
        with pytest.raises(RuntimeError, match="Capture is closed"):
            cap.read()

    def test_exit_closes_capture(
        self,
        win32_pid_and_hwnd: None,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        del win32_pid_and_hwnd, fake_windows_capture
        with Capture() as cap:
            pass

        with pytest.raises(RuntimeError, match="Capture is closed"):
            cap.read()

    def test_exit_does_not_suppress_exception(
        self,
        win32_pid_and_hwnd: None,
        fake_windows_capture: type[FakeWindowsCapture],
    ):
        # The context manager must propagate exceptions from the with-
        # block. Suppression would silently swallow real failures and
        # is not the contract we want.
        del win32_pid_and_hwnd, fake_windows_capture

        class _Sentinel(Exception):
            pass

        with pytest.raises(_Sentinel):
            with Capture():
                raise _Sentinel("boom")


# ---------------------------------------------------------------------------
# X11 backend
# ---------------------------------------------------------------------------


@dataclass
class _X11Patches:
    """Bundle of fakes returned by the X11 happy-path fixture."""

    display: FakeXDisplay
    window: FakeXWindow
    pixmap: FakePixmap


@pytest.fixture
def patch_x11_backend(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> _X11Patches:
    """Wire up the standard happy-path fakes for an X11 ``Capture``.

    Patches ``find_pid``, ``open_x11_display``, ``find_vrchat_window``,
    and the three ``composite.*`` calls. Returns the underlying fakes
    so tests can layer additional state (e.g. a different geometry,
    a side effect on ``get_image``) on top.

    The pixmap fake honours whatever width / height ``get_image`` is
    invoked with, so tests can mutate ``window.geometry`` after the
    capture has started without re-patching ``name_window_pixmap``.
    """
    monkeypatch.setenv("DISPLAY", ":0")

    width = 100
    height = 50
    pid = 4242

    fake_display = FakeXDisplay()
    fake_window = FakeXWindow(
        wid=1, pid=pid, geometry=FakeXGeometry(width=width, height=height)
    )
    fake_pixmap = FakePixmap(width=width, height=height)

    mocker.patch("vrcpilot.capture.linux.find_pid", return_value=pid)
    mocker.patch("vrcpilot.capture.linux.open_x11_display", return_value=fake_display)
    mocker.patch("vrcpilot.capture.linux.find_vrchat_window", return_value=fake_window)
    mocker.patch("vrcpilot.capture.linux.composite.query_version")
    mocker.patch("vrcpilot.capture.linux.composite.redirect_window")
    mocker.patch(
        "vrcpilot.capture.linux.composite.name_window_pixmap",
        return_value=fake_pixmap,
    )

    return _X11Patches(display=fake_display, window=fake_window, pixmap=fake_pixmap)


class TestCaptureX11:
    """X11 / Composite backend behaviour."""

    pytestmark = only_linux

    def test_lifecycle_returns_rgb_frame(self, patch_x11_backend: _X11Patches):
        # Provide a constant BGRA buffer; verify ``read`` returns a
        # contiguous (H, W, 3) RGB array of the right shape. The pixmap
        # fake honours the width / height passed to ``get_image`` so a
        # resize-via-geometry alone is enough to exercise the reshape.
        patch_x11_backend.window.geometry = FakeXGeometry(width=4, height=3)

        with Capture() as cap:
            frame = cap.read()

        assert isinstance(frame, np.ndarray)
        assert frame.shape == (3, 4, 3)
        assert frame.dtype == np.uint8
        assert frame.flags["C_CONTIGUOUS"]

    def test_init_raises_on_wayland_native(self, monkeypatch: pytest.MonkeyPatch):
        # Capture must raise on native Wayland (no X server reachable),
        # *not* warn-and-return-None. Single-shot screenshot has the
        # warning path; continuous capture is fail-fast by design.
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("DISPLAY", raising=False)

        with pytest.raises(RuntimeError, match="native Wayland is not supported"):
            Capture()

    def test_init_raises_when_vrchat_not_running(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DISPLAY", ":0")
        mocker.patch("vrcpilot.capture.linux.find_pid", return_value=None)

        with pytest.raises(RuntimeError, match="VRChat is not running"):
            Capture()

    def test_init_raises_when_display_unavailable(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DISPLAY", ":0")
        mocker.patch("vrcpilot.capture.linux.find_pid", return_value=4242)
        mocker.patch("vrcpilot.capture.linux.open_x11_display", return_value=None)

        with pytest.raises(RuntimeError, match="X11 display unavailable"):
            Capture()

    def test_init_raises_when_window_not_found(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ):
        # If the window can't be located we must close the display we
        # just opened before re-raising; otherwise the X server socket
        # leaks across each retry.
        monkeypatch.setenv("DISPLAY", ":0")
        fake_display = FakeXDisplay()
        mocker.patch("vrcpilot.capture.linux.find_pid", return_value=4242)
        mocker.patch(
            "vrcpilot.capture.linux.open_x11_display",
            return_value=fake_display,
        )
        mocker.patch("vrcpilot.capture.linux.find_vrchat_window", return_value=None)

        with pytest.raises(RuntimeError, match="window is not yet mapped"):
            Capture()
        assert fake_display.close_calls == 1

    def test_init_raises_on_composite_xerror(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DISPLAY", ":0")
        fake_display = FakeXDisplay()
        fake_window = FakeXWindow()
        mocker.patch("vrcpilot.capture.linux.find_pid", return_value=4242)
        mocker.patch(
            "vrcpilot.capture.linux.open_x11_display",
            return_value=fake_display,
        )
        mocker.patch(
            "vrcpilot.capture.linux.find_vrchat_window",
            return_value=fake_window,
        )

        xerr_cls = make_xerror_subclass()
        mocker.patch(
            "vrcpilot.capture.linux.composite.query_version",
            side_effect=xerr_cls(),
        )

        with pytest.raises(RuntimeError, match="X11 Composite extension"):
            Capture()
        assert fake_display.close_calls == 1

    def test_read_raises_on_invalid_geometry(self, patch_x11_backend: _X11Patches):
        # A window can resize to zero between init and the next read; we
        # surface that as a typed RuntimeError instead of producing an
        # empty array, which would mask the underlying bug.
        cap = Capture()
        try:
            patch_x11_backend.window.geometry = FakeXGeometry(width=0, height=0)
            with pytest.raises(RuntimeError, match="invalid geometry"):
                cap.read()
        finally:
            cap.close()

    def test_read_translates_xerror(self, patch_x11_backend: _X11Patches):
        # Inject an XError on the get_image call. Capture must wrap it as
        # a RuntimeError -- callers catch ``RuntimeError`` and decide to
        # retry; raw ``Xlib.error.XError`` would force them to import
        # python-xlib just for error handling.
        xerr_cls = make_xerror_subclass()
        patch_x11_backend.pixmap.get_image_side_effect = xerr_cls()

        with Capture() as cap:
            with pytest.raises(RuntimeError, match="X11 capture failed"):
                cap.read()

    def test_close_is_idempotent(self, patch_x11_backend: _X11Patches):
        cap = Capture()
        cap.close()
        cap.close()
        cap.close()

        # Display.close runs only on the first ``Capture.close`` call;
        # idempotence is enforced by the ``_closed`` flag.
        assert patch_x11_backend.display.close_calls == 1

    def test_read_after_close_raises(self, patch_x11_backend: _X11Patches):
        del patch_x11_backend
        cap = Capture()
        cap.close()
        with pytest.raises(RuntimeError, match="Capture is closed"):
            cap.read()
