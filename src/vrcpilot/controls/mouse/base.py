"""Cross-platform :class:`MouseButton` enum and :class:`Mouse` ABC.

Lives in its own module so the platform-specific backends
(:mod:`vrcpilot.controls.mouse.windows`,
:mod:`vrcpilot.controls.mouse.linux`) can import it without dragging
each other in. The dispatcher in :mod:`vrcpilot.controls.mouse`
imports the right backend lazily on first use.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import StrEnum

from vrcpilot.controls.errors import VRChatNotRunningError
from vrcpilot.controls.guard import ensure_target
from vrcpilot.geometry import get_vrchat_window_rect


class MouseButton(StrEnum):
    """Mouse button identifiers.

    Values are the lower-case strings ``pydirectinput`` expects on its
    ``button=`` kwarg, so the Win32 backend forwards ``button.value``
    straight through. The Linux backend maps each member via
    :data:`vrcpilot.controls.mouse.linux._BUTTON_MAP`. Being a
    :class:`enum.StrEnum`, members compare equal to their string value,
    which lets ``argparse(type=MouseButton)`` accept ``left`` /
    ``right`` / ``middle`` directly from the CLI.
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

        With ``relative=False`` (default), ``(x, y)`` are VRChat
        window-local pixels: ``(0, 0)`` is the top-left of the VRChat
        window. This lets coordinates from
        :func:`vrcpilot.ocr.ocr` / :func:`vrcpilot.detect.detect` feed
        straight in without translation.

        With ``relative=True``, ``(x, y)`` are mouse deltas and the
        VRChat window is not consulted.

        Out-of-window coordinates are forwarded to the OS as-is rather
        than clamped — callers driving drag gestures or off-screen
        parking rely on that pass-through.

        Raises:
            VRChatNotRunningError: ``relative=False`` and the VRChat
                window cannot be located, so window-local coordinates
                cannot be resolved. ``focus=False`` does not suppress
                this — the lookup is required to interpret ``(x, y)``.
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

        Raises :class:`VRChatNotRunningError` when the VRChat window
        cannot be located, since the translation has no defined answer
        without a window origin.
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
