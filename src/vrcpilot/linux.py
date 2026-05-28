"""X11 helpers shared between window control and screen capture."""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError

from collections.abc import Iterator
from contextlib import contextmanager

import Xlib.display
import Xlib.error
from Xlib import X
from Xlib.xobject.drawable import Window as _XWindow


def open_x11_display() -> Xlib.display.Display | None:
    """Open an X11 display for callers that manage the connection lifetime.

    The caller owns the returned display and must eventually
    :meth:`~Xlib.display.Display.close` it; for block-scoped use prefer
    :func:`x11_display` to avoid leaking on early returns.

    Returns:
        ``None`` when the X server is unreachable: ``DISPLAY`` unset,
        no server listening, or a stale ``XAUTHORITY`` (the common SSH
        symptom). Programming errors still propagate.
    """
    try:
        return Xlib.display.Display()
    except (
        Xlib.error.DisplayError,
        Xlib.error.XauthError,
        Xlib.error.ConnectionClosedError,
        OSError,
    ):
        return None


@contextmanager
def x11_display() -> Iterator[Xlib.display.Display | None]:
    """Open an X11 display scoped to a ``with`` block.

    Yields:
        A live display, or ``None`` on connection failure (same surface
        as :func:`open_x11_display`). Yielding ``None`` rather than
        raising lets callers handle "no display" as data inside the
        block.
    """
    display = open_x11_display()
    if display is None:
        yield None
        return
    try:
        yield display
    finally:
        display.close()


def find_vrchat_window(display: Xlib.display.Display, pid: int) -> _XWindow | None:
    """Locate the EWMH-managed top-level window owned by ``pid``.

    Only EWMH-compliant WMs are supported because the lookup relies on
    ``_NET_CLIENT_LIST`` plus ``_NET_WM_PID``. Windows that disappear
    between the snapshot and the property read are silently skipped
    (race against the WM during window teardown).

    Returns:
        The matching window, or ``None`` when no entry in
        ``_NET_CLIENT_LIST`` advertises that PID.
    """
    root = display.screen().root
    net_client_list = display.intern_atom("_NET_CLIENT_LIST")
    net_wm_pid = display.intern_atom("_NET_WM_PID")

    client_list_prop = root.get_full_property(net_client_list, X.AnyPropertyType)
    if client_list_prop is None:
        return None

    for wid in client_list_prop.value:
        try:
            window = display.create_resource_object("window", int(wid))
            pid_prop = window.get_full_property(net_wm_pid, X.AnyPropertyType)
        except Xlib.error.BadWindow:
            # Window disappeared between _NET_CLIENT_LIST snapshot and the
            # property read — skip and continue scanning.
            continue
        if pid_prop is None:
            continue
        values = pid_prop.value
        if len(values) > 0 and int(values[0]) == pid:
            return window
    return None


def get_window_rect(
    display: Xlib.display.Display, window: _XWindow
) -> tuple[int, int, int, int] | None:
    """Report ``window``'s rectangle in root-screen coordinates for capture.

    Coordinates are sign-inverted from the ``translate_coords`` reply
    because python-xlib empirically returns the negation of the window
    origin; the resulting rect aligns with the region ``Capture`` grabs
    (see commit ``77a6422``).

    Returns:
        ``(x, y, width, height)``, or ``None`` when the window has been
        destroyed mid-call or has degenerate (non-positive) geometry.
    """
    try:
        coords = window.translate_coords(display.screen().root, 0, 0)
        geom = window.get_geometry()
    except Xlib.error.XError:
        return None
    width = int(geom.width)
    height = int(geom.height)
    if width <= 0 or height <= 0:
        return None
    return (-int(coords.x), -int(coords.y), width, height)
