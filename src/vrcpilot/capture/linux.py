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
from vrcpilot.session import is_wayland_native

from .base import CaptureBackend


class X11CaptureBackend(CaptureBackend):
    """Off-screen X11 capture backend for the VRChat window.

    Redirects the target window to off-screen storage via the Composite
    extension so :meth:`read` returns pixels regardless of stacking
    order — i.e. capture works even when VRChat is occluded or
    minimised, without ever raising the window.
    """

    _display: Xlib.display.Display
    _window: _XWindow

    def __init__(self, *, pid: int) -> None:
        if is_wayland_native():
            raise RuntimeError(
                "Capture requires X11 or XWayland; native Wayland is not supported",
            )

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
        """Synchronously re-grab the off-screen pixmap on every call.

        Synchronous (no waiter / no timeout) because Composite gives us
        the current pixels on demand; there is no producer thread to
        race with as on Windows.

        Raises:
            RuntimeError: Window geometry collapsed to zero (typically
                during resize) or the X server returned an XError mid
                grab. The session is not invalidated — callers may retry.
        """
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
        """Close the held X display connection.

        Deliberately does not unredirect: the redirect is per-client and
        the server drops it automatically when the connection closes,
        so an explicit unredirect would just risk an XError on a window
        that may already be gone.
        """
        try:
            self._display.close()
        except Exception as exc:  # noqa: BLE001 - close() must not raise
            warnings.warn(
                f"X11 display close failed: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
