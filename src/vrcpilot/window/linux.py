"""X11/XWayland implementation of focus/unfocus for the VRChat window."""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError

import warnings

import Xlib.error
import Xlib.protocol.event
from Xlib import X

from vrcpilot.linux import find_vrchat_window, x11_display
from vrcpilot.session import is_wayland_native


def focus_window(*, pid: int) -> bool:
    """X11/XWayland implementation of :func:`vrcpilot.window.focus`."""
    if is_wayland_native():
        warnings.warn(
            "Wayland native session detected; "
            "focus()/unfocus() require X11 or XWayland.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    with x11_display() as display:
        if display is None:
            return False
        window = find_vrchat_window(display, pid)
        if window is None:
            return False
        try:
            net_active = display.intern_atom("_NET_ACTIVE_WINDOW")
            root = display.screen().root
            event = Xlib.protocol.event.ClientMessage(
                window=window,
                client_type=net_active,
                # 32-bit format payload per EWMH: source=2 (pager /
                # automation tool), timestamp=CurrentTime, currently
                # active window=0 (unknown), remaining slots=0.
                data=(32, [2, X.CurrentTime, 0, 0, 0]),
            )
            mask = X.SubstructureRedirectMask | X.SubstructureNotifyMask
            root.send_event(event, event_mask=mask)
            display.flush()
        except Xlib.error.XError:
            return False
        return True


def is_window_foreground(*, pid: int) -> bool:
    """X11/XWayland implementation of :func:`vrcpilot.window.is_foreground`."""
    if is_wayland_native():
        warnings.warn(
            "Wayland native session detected; "
            "is_foreground() requires X11 or XWayland.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    with x11_display() as display:
        if display is None:
            return False
        window = find_vrchat_window(display, pid)
        if window is None:
            return False
        try:
            net_active = display.intern_atom("_NET_ACTIVE_WINDOW")
            root = display.screen().root
            active_prop = root.get_full_property(net_active, X.AnyPropertyType)
        except Xlib.error.XError:
            return False
        if active_prop is None:
            return False
        values = active_prop.value
        if len(values) == 0:
            return False
        return int(values[0]) == int(window.id)


def unfocus_window(*, pid: int) -> bool:
    """X11/XWayland implementation of :func:`vrcpilot.window.unfocus`."""
    if is_wayland_native():
        warnings.warn(
            "Wayland native session detected; "
            "focus()/unfocus() require X11 or XWayland.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    with x11_display() as display:
        if display is None:
            return False
        window = find_vrchat_window(display, pid)
        if window is None:
            return False
        try:
            # ConfigureWindow with stack_mode=Below lowers the window in
            # the z-order without changing input focus — the X11
            # equivalent of SetWindowPos(HWND_BOTTOM, SWP_NOACTIVATE).
            window.configure(stack_mode=X.Below)
            display.flush()
        except Xlib.error.XError:
            return False
        return True
