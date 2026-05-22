"""X11 Composite backend for :class:`vrcpilot.Capture`.

Re-grabs the off-screen pixmap on every :meth:`read` so the returned
frame reflects the window's current state even when occluded.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError

import warnings
from typing import Any, cast, override

import numpy as np
import Xlib.display
import Xlib.error
from Xlib import X
from Xlib.ext import composite
from Xlib.xobject.drawable import Window as _XWindow

from vrcpilot.linux import find_vrchat_window, open_x11_display
from vrcpilot.process import find_pid
from vrcpilot.session import is_wayland_native

from .base import CaptureBackend


class X11CaptureBackend(CaptureBackend):
    """X11 Composite capture session: holds the display + redirected window."""

    _display: Xlib.display.Display
    _window: _XWindow

    def __init__(self) -> None:
        if is_wayland_native():
            raise RuntimeError(
                "Capture requires X11 or XWayland; native Wayland is not supported",
            )

        pid = find_pid()
        if pid is None:
            raise RuntimeError("VRChat is not running")

        display = open_x11_display()
        if display is None:
            raise RuntimeError("X11 display unavailable")

        try:
            window = find_vrchat_window(display, pid)
            if window is None:
                raise RuntimeError("VRChat top-level window is not yet mapped")

            # Verify the server speaks Composite -- raises XError when
            # the extension isn't loaded so we can fail fast.
            try:
                composite.query_version(display)
            except Xlib.error.XError as exc:
                raise RuntimeError(
                    f"X11 Composite extension not available: {exc}",
                ) from exc

            try:
                # Redirect the window to off-screen storage so we can read
                # its pixels regardless of stacking order. Idempotent when
                # a compositor (picom, mutter, kwin...) already redirects.
                # python-xlib stubs declare the ``update`` parameter as a
                # callable, but the protocol value is the int constant
                # ``RedirectAutomatic`` -- launder through ``Any`` rather
                # than fight the upstream stub error.
                composite.redirect_window(
                    window, cast(Any, composite.RedirectAutomatic)
                )
            except Xlib.error.XError as exc:
                raise RuntimeError(f"Failed to redirect window: {exc}") from exc
        except BaseException:
            # Any failure between display open and successful redirect must
            # release the connection; otherwise an exception during init
            # leaks the X server socket.
            try:
                display.close()
            except Exception:  # noqa: BLE001 - cleanup must not mask the cause
                pass
            raise

        self._display = display
        self._window = window

    @override
    def read(self) -> np.ndarray:
        """Re-grab the window pixmap through Composite and return RGB
        ndarray."""
        try:
            geom = self._window.get_geometry()
            width = int(geom.width)
            height = int(geom.height)
            if width <= 0 or height <= 0:
                raise RuntimeError("Window has invalid geometry")
            pixmap = composite.name_window_pixmap(self._window)
            try:
                reply = pixmap.get_image(0, 0, width, height, X.ZPixmap, 0xFFFFFFFF)
            finally:
                pixmap.free()
        except Xlib.error.XError as exc:
            raise RuntimeError(f"X11 capture failed: {exc}") from exc

        bgra = np.frombuffer(reply.data, dtype=np.uint8).reshape(height, width, 4)
        return np.ascontiguousarray(bgra[..., 2::-1])

    @override
    def close(self) -> None:
        """Close the held X display connection (no unredirect, no pixmap)."""
        try:
            self._display.close()
        except Exception as exc:  # noqa: BLE001 - close() must not raise
            warnings.warn(
                f"X11 display close failed: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
