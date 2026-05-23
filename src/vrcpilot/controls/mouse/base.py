"""Cross-platform :class:`MouseButton` enum and :class:`Mouse` ABC.

Lives in its own module so platform backends can import it without
dragging each other in.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import StrEnum

from vrcpilot.controls.guard import ensure_target
from vrcpilot.geometry import get_vrchat_window_rect
from vrcpilot.process import VRChatNotRunningError


class MouseButton(StrEnum):
    """Mouse button identifiers.

    Values are the lower-case strings ``pydirectinput`` expects, which
    also lets ``argparse(type=MouseButton)`` accept ``left`` / ``right``
    / ``middle`` directly from the CLI.
    """

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class Mouse(ABC):
    """Mouse ABC: runs :func:`ensure_target`, then delegates to ``_do_*``.

    Every public method accepts a keyword-only ``pid`` to target a
    specific VRChat instance when multiple are running. ``focus=False``
    is an optimisation flag for hot loops where the caller already
    ensures VRChat is foreground: it skips :func:`ensure_target`
    entirely, including the internal :func:`vrcpilot.process.resolve_pid`
    that scans ``psutil.process_iter`` (too expensive per frame). The
    only exception is :meth:`move` on the absolute path -- the window
    rect lookup needs a PID, and when ``pid`` is omitted there
    :func:`get_vrchat_window_rect` runs the resolve itself (this path is
    rare in practice, so the cost is acceptable).
    """

    def move(
        self,
        x: int,
        y: int,
        *,
        relative: bool = False,
        focus: bool = True,
        pid: int | None = None,
    ) -> None:
        """Move the cursor.

        Default is VRChat window-local pixels (``(0, 0)`` = window
        top-left), so coordinates from :func:`vrcpilot.ocr.ocr` /
        :func:`vrcpilot.detect.detect` feed in directly. With
        ``relative=True``, ``(x, y)`` are deltas and the window is not
        consulted. Out-of-window coordinates are forwarded as-is, never
        clamped — drag gestures and off-screen parking rely on that.

        ``pid`` selects the target VRChat instance when multiple are
        running. With ``focus=True`` the PID resolved by
        :func:`ensure_target` is reused for the window-rect lookup so a
        single call cannot race against VRChat exiting between the two
        helpers. With ``focus=False`` the supplied ``pid`` (possibly
        ``None``) is forwarded directly to :meth:`_to_desktop` /
        :func:`get_vrchat_window_rect`, which only resolves on the
        absolute path when ``pid`` was omitted.

        Raises :class:`VRChatNotRunningError` when ``relative=False``
        and the VRChat window cannot be located (``focus=False`` does
        not suppress this — the lookup is needed to interpret ``(x, y)``).
        """
        if focus:
            resolved: int | None = ensure_target(pid=pid)
        else:
            # Hot-loop optimisation: caller guarantees focus, so we
            # skip every PID lookup. The supplied pid (may be None) is
            # forwarded as-is.
            resolved = pid
        if relative:
            self._do_move(x, y, relative=True)
            return
        dx, dy = self._to_desktop(x, y, pid=resolved)
        self._do_move(dx, dy, relative=False)

    def _to_desktop(self, x: int, y: int, *, pid: int | None) -> tuple[int, int]:
        """Translate window-local ``(x, y)`` to desktop pixels.

        ``pid`` is forwarded to :func:`get_vrchat_window_rect`; when
        ``None``, the rect helper runs its own
        :func:`vrcpilot.process.resolve_pid` (so a multi-instance state
        still surfaces as :class:`VRChatMultipleInstancesError` on the
        rare ``focus=False`` + absolute path).

        Raises :class:`VRChatNotRunningError` when the window cannot be
        located, since the translation is undefined without an origin.
        """
        rect = get_vrchat_window_rect(pid=pid)
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
        pid: int | None = None,
    ) -> None:
        """Click ``buttons`` simultaneously, repeated ``count`` times.

        ``duration`` is the per-cycle hold in seconds; use 0.02 – 0.05
        when VRChat / Unity drops zero-length presses. Cycles run
        back-to-back with no inter-cycle delay. Empty ``buttons``
        defaults to :attr:`MouseButton.LEFT`. ``pid`` selects the
        target VRChat instance when multiple are running;
        ``focus=False`` skips every PID lookup (hot-loop fast path).
        """
        if focus:
            ensure_target(pid=pid)
        if not buttons:
            buttons = (MouseButton.LEFT,)
        for _ in range(count):
            for b in buttons:
                self._do_press(b)
            if duration > 0:
                time.sleep(duration)
            for b in reversed(buttons):
                self._do_release(b)

    def press(
        self,
        *buttons: MouseButton,
        focus: bool = True,
        pid: int | None = None,
    ) -> None:
        """Press and hold ``buttons`` until a matching :meth:`release`.

        Half-action; only valid within a single Python process. Empty
        ``buttons`` defaults to :attr:`MouseButton.LEFT`. ``pid``
        selects the target VRChat instance when multiple are running;
        ``focus=False`` skips every PID lookup (hot-loop fast path).
        """
        if focus:
            ensure_target(pid=pid)
        if not buttons:
            buttons = (MouseButton.LEFT,)
        for b in buttons:
            self._do_press(b)

    def release(
        self,
        *buttons: MouseButton,
        focus: bool = True,
        pid: int | None = None,
    ) -> None:
        """Release buttons previously held with :meth:`press`.

        Reversed release order makes ``press(*bs)`` / ``release(*bs)``
        LIFO. Empty ``buttons`` defaults to :attr:`MouseButton.LEFT`.
        ``pid`` selects the target VRChat instance when multiple are
        running; ``focus=False`` skips every PID lookup (hot-loop fast
        path).
        """
        if focus:
            ensure_target(pid=pid)
        if not buttons:
            buttons = (MouseButton.LEFT,)
        for b in reversed(buttons):
            self._do_release(b)

    def scroll(
        self, amount: int, *, focus: bool = True, pid: int | None = None
    ) -> None:
        """Scroll vertically by ``amount`` notches (positive = down).

        ``pid`` selects the target VRChat instance when multiple are
        running; ``focus=False`` skips every PID lookup (hot-loop fast
        path).
        """
        if focus:
            ensure_target(pid=pid)
        self._do_scroll(amount)

    @abstractmethod
    def _do_move(self, x: int, y: int, *, relative: bool) -> None: ...

    @abstractmethod
    def _do_press(self, button: MouseButton) -> None: ...

    @abstractmethod
    def _do_release(self, button: MouseButton) -> None: ...

    @abstractmethod
    def _do_scroll(self, amount: int) -> None: ...
