"""Synthetic mouse input for VRChat."""

from __future__ import annotations

import ctypes
import sys
import time
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, override

from vrcpilot.geometry import get_vrchat_window_rect

from .errors import VRChatNotRunningError
from .guard import ensure_target

# inputtino's scroll API takes distance in 120-per-notch high-resolution
# units; we expose plain notches and multiply on the way down.
_SCROLL_NOTCH = 120


class MouseButton(StrEnum):
    """Mouse button identifiers.

    Values are the lower-case strings ``pydirectinput`` expects on its
    ``button=`` kwarg, so the Win32 backend forwards ``button.value``
    straight through. The Linux backend maps each member via
    :data:`_BUTTON_MAP`. Being a :class:`enum.StrEnum`, members compare
    equal to their string value, which lets ``argparse(type=MouseButton)``
    accept ``left`` / ``right`` / ``middle`` directly from the CLI.
    """

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class Mouse(ABC):
    """Mouse ABC: runs :func:`ensure_target`, then delegates to ``_do_*``."""

    def move(
        self, x: int, y: int, *, relative: bool = False, focus: bool = True
    ) -> None:
        """Move the cursor.

        With ``relative=False`` (default), ``(x, y)`` are interpreted as
        VRChat window-local pixels: ``(0, 0)`` is the top-left of the
        VRChat window. The values are translated to desktop-absolute
        coordinates via :meth:`_to_desktop` before reaching the backend.

        With ``relative=True``, ``(x, y)`` are mouse deltas (relative
        movement) and are passed through to the backend unchanged.

        Out-of-window coordinates (negative or beyond the window size)
        are intentionally not rejected: the desktop-absolute value is
        forwarded to the OS as-is, matching the previous
        desktop-absolute semantics for points outside any monitor.

        Raises:
            VRChatNotRunningError: ``relative=False`` and the VRChat
                window cannot be located, so window-local coordinates
                cannot be resolved.
        """
        if focus:
            ensure_target()
        if relative:
            self._do_move(x, y, relative=True)
            return
        dx, dy = self._to_desktop(x, y)
        self._do_move(dx, dy, relative=False)

    def _to_desktop(self, x: int, y: int) -> tuple[int, int]:
        """Translate VRChat window-local ``(x, y)`` to desktop pixels.

        Looks up the current VRChat window rectangle via
        :func:`vrcpilot.geometry.get_vrchat_window_rect` and returns
        ``(x + wx, y + wy)`` where ``(wx, wy)`` is the window origin.

        Raises:
            VRChatNotRunningError: The VRChat window cannot be located.
        """
        rect = get_vrchat_window_rect()
        if rect is None:
            raise VRChatNotRunningError(
                "VRChat window not found; cannot resolve window-local coordinates"
            )
        wx, wy, _, _ = rect
        return x + wx, y + wy

    def click(
        self,
        *buttons: MouseButton,
        count: int = 1,
        duration: float = 0.0,
        focus: bool = True,
    ) -> None:
        """Click one or more buttons simultaneously, ``count`` times.

        ``buttons`` are pressed left-to-right, held for ``duration``
        seconds (skipped when ``duration == 0``), then released in
        reverse order. The combo is repeated ``count`` times back-to-back
        with no inter-cycle delay. ``duration`` is the down-to-up hold
        per cycle in seconds; use ``0.02``-``0.05`` when VRChat / Unity
        drops zero-length presses.

        Calling ``click()`` with no ``buttons`` is treated as
        ``click(MouseButton.LEFT)`` for back-compat with the previous
        single-button signature.
        """
        if focus:
            ensure_target()
        if not buttons:
            buttons = (MouseButton.LEFT,)
        for _ in range(count):
            for b in buttons:
                self._do_press(b)
            if duration > 0:
                time.sleep(duration)
            for b in reversed(buttons):
                self._do_release(b)

    def press(self, *buttons: MouseButton, focus: bool = True) -> None:
        """Press and hold one or more buttons until a matching :meth:`release`.

        Buttons are pressed left-to-right. Empty argument list falls
        back to :attr:`MouseButton.LEFT` for back-compat.
        """
        if focus:
            ensure_target()
        if not buttons:
            buttons = (MouseButton.LEFT,)
        for b in buttons:
            self._do_press(b)

    def release(self, *buttons: MouseButton, focus: bool = True) -> None:
        """Release one or more buttons previously held with :meth:`press`.

        Buttons are released in reverse order so a paired ``press(*bs)``
        / ``release(*bs)`` follows LIFO stack semantics. Empty argument
        list falls back to :attr:`MouseButton.LEFT` for back-compat.
        """
        if focus:
            ensure_target()
        if not buttons:
            buttons = (MouseButton.LEFT,)
        for b in reversed(buttons):
            self._do_release(b)

    def scroll(self, amount: int, *, focus: bool = True) -> None:
        """Scroll vertically by ``amount`` notches (positive = down)."""
        if focus:
            ensure_target()
        self._do_scroll(amount)

    @abstractmethod
    def _do_move(self, x: int, y: int, *, relative: bool) -> None: ...

    @abstractmethod
    def _do_press(self, button: MouseButton) -> None: ...

    @abstractmethod
    def _do_release(self, button: MouseButton) -> None: ...

    @abstractmethod
    def _do_scroll(self, amount: int) -> None: ...


# Linux backend ------------------------------------------------------------

if sys.platform == "linux":
    import inputtino
    import mss

    _BUTTON_MAP: dict[MouseButton, inputtino.MouseButton] = {
        MouseButton.LEFT: inputtino.MouseButton.LEFT,
        MouseButton.MIDDLE: inputtino.MouseButton.MIDDLE,
        MouseButton.RIGHT: inputtino.MouseButton.RIGHT,
    }

    class LinuxMouse(Mouse):
        """``inputtino``-backed :class:`Mouse`.

        Opens ``/dev/uinput`` at construction; inputtino raises
        :class:`RuntimeError` if the caller lacks permission. Screen
        size for absolute moves is captured once from ``mss.monitors[0]``
        (whole-desktop bounding box).
        """

        def __init__(self) -> None:
            self._imp = inputtino.Mouse()
            # Match screenshot.py: explicit instantiate / close (not
            # the context manager) so test fakes can be plain mocks
            # without implementing __enter__ / __exit__.
            sct = mss.MSS()
            try:
                bbox = sct.monitors[0]
                self._screen_w = int(bbox["width"])
                self._screen_h = int(bbox["height"])
            finally:
                sct.close()

        @override
        def _do_move(self, x: int, y: int, *, relative: bool) -> None:
            if relative:
                self._imp.move(x, y)
            else:
                self._imp.move_abs(x, y, self._screen_w, self._screen_h)

        @override
        def _do_press(self, button: MouseButton) -> None:
            self._imp.press(_BUTTON_MAP[button])

        @override
        def _do_release(self, button: MouseButton) -> None:
            self._imp.release(_BUTTON_MAP[button])

        @override
        def _do_scroll(self, amount: int) -> None:
            self._imp.scroll_vertical(amount * _SCROLL_NOTCH)


# Win32 backend ------------------------------------------------------------

if sys.platform == "win32":
    # pydirectinput ships no stubs; alias to Any once so call sites stay
    # clean instead of needing reportUnknownMemberType ignores per call.
    import pydirectinput as _pydirectinput_module  # pyright: ignore[reportMissingTypeStubs]

    pydirectinput: Any = _pydirectinput_module

    # Disable pydirectinput's "cursor at (0, 0) panic" — VRChat workflows
    # legitimately move the cursor to corners and we do not want a hard
    # exit from a synthetic input call.
    pydirectinput.FAILSAFE = False

    # MOUSEEVENTF_WHEEL is the SendInput flag for vertical wheel events.
    # pydirectinput 1.0.4 does not ship a scroll() helper, so we
    # synthesize the event using its already-imported ctypes structures.
    _MOUSEEVENTF_WHEEL = 0x0800
    _WHEEL_DELTA = 120

    def _scroll_wheel(amount: int) -> None:
        """Synthesize a vertical wheel event via ``SendInput``.

        Win32 wheel sign convention: positive = up. Caller is expected
        to have already sign-flipped to match the public API
        (positive = down).
        """
        extra = ctypes.c_ulong(0)
        ii = pydirectinput.Input_I()
        ii.mi = pydirectinput.MouseInput(
            0,
            0,
            ctypes.c_ulong(amount * _WHEEL_DELTA).value,
            _MOUSEEVENTF_WHEEL,
            0,
            ctypes.pointer(extra),
        )
        inp = pydirectinput.Input(ctypes.c_ulong(0), ii)
        pydirectinput.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))

    class Win32Mouse(Mouse):
        """``pydirectinput``-backed :class:`Mouse`.

        Uses Windows screen coordinates directly (no mss capture).
        """

        @override
        def _do_move(self, x: int, y: int, *, relative: bool) -> None:
            if relative:
                pydirectinput.moveRel(x, y)
            else:
                pydirectinput.moveTo(x, y)

        @override
        def _do_press(self, button: MouseButton) -> None:
            pydirectinput.mouseDown(button=button)

        @override
        def _do_release(self, button: MouseButton) -> None:
            pydirectinput.mouseUp(button=button)

        @override
        def _do_scroll(self, amount: int) -> None:
            # Public API: positive = down. Win32: positive = up. Flip.
            _scroll_wheel(-amount)


# Lazy singleton -----------------------------------------------------------

_instance: Mouse | None = None


def _get() -> Mouse:
    """Return the platform backend, constructing it on first call.

    Deferred so import does not eagerly open ``/dev/uinput`` (Linux).
    """
    global _instance
    if _instance is None:
        if sys.platform == "win32":
            _instance = Win32Mouse()
        elif sys.platform == "linux":
            _instance = LinuxMouse()
        else:
            raise NotImplementedError(
                f"controls.mouse is not supported on {sys.platform}"
            )
    return _instance


# Module functions ---------------------------------------------------------


def move(x: int, y: int, *, relative: bool = False, focus: bool = True) -> None:
    """See :meth:`Mouse.move`."""
    _get().move(x, y, relative=relative, focus=focus)


def click(
    *buttons: MouseButton,
    count: int = 1,
    duration: float = 0.0,
    focus: bool = True,
) -> None:
    """See :meth:`Mouse.click`."""
    _get().click(*buttons, count=count, duration=duration, focus=focus)


def press(*buttons: MouseButton, focus: bool = True) -> None:
    """See :meth:`Mouse.press`."""
    _get().press(*buttons, focus=focus)


def release(*buttons: MouseButton, focus: bool = True) -> None:
    """See :meth:`Mouse.release`."""
    _get().release(*buttons, focus=focus)


def scroll(amount: int, *, focus: bool = True) -> None:
    """See :meth:`Mouse.scroll`."""
    _get().scroll(amount, focus=focus)
