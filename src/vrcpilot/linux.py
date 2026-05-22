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
    """Open an X11 display without a context manager.

    For long-lived connections the caller must eventually call
    :meth:`Xlib.display.Display.close`. For block-scoped use prefer
    :func:`x11_display`. Returns ``None`` on connection failure (X
    server unreachable, ``DISPLAY`` unset, missing/stale
    ``XAUTHORITY``).
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
    """Open an X11 display for the duration of a ``with`` block.

    Yields ``None`` on connection failure (see :func:`open_x11_display`
    for the failure surface — common SSH symptom is a stale
    ``XAUTHORITY``).
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
    """Return the EWMH-managed window owned by *pid*, or ``None``.

    Scans ``_NET_CLIENT_LIST`` and matches each entry's ``_NET_WM_PID``;
    windows that disappear mid-iteration (``BadWindow``) are skipped.
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
    """Return ``(x, y, width, height)`` of *window* in root screen coords.

    The ``translate_coords`` reply's ``x`` / ``y`` are empirically the
    negation of the window's screen-space origin under python-xlib, so
    the sign is inverted here (mirrors the prior mss-based behaviour;
    see commit ``77a6422``). Returns ``None`` when the window has
    disappeared or has degenerate geometry.
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
