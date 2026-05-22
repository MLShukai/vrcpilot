"""VRChat OSC input-controller view.

Exposes every ``/input/*`` and ``/chatbox/*`` address documented at
<https://docs.vrchat.com/docs/osc-as-input-controller> in three flavors:

* **Axes** — float in ``[-1.0, 1.0]`` (validated by ``send_float``).
* **Tap** — single-shot ``1 -> sleep(button_hold) -> 0`` transitions.
* **Hold** — explicit ``active=True/False`` press/release.
"""

from __future__ import annotations

import time
from typing import Final

from . import sender

#: Maximum text length accepted by ``/chatbox/input`` per VRChat docs.
CHATBOX_MAX_LENGTH: Final[int] = 144


class InputController:
    """OSC input-controller view bound to a single :class:`OscSender`.

    ``button_hold`` is the seconds a tap stays "pressed"; ``0.0`` skips
    the sleep (the off message still fires). Negative values are
    rejected at construction time, not on the first tap.
    """

    def __init__(self, sender: sender.OscSender, *, button_hold: float = 0.05) -> None:
        if button_hold < 0.0:
            raise ValueError(f"button_hold must be >= 0, got {button_hold}")
        self._sender = sender
        self._button_hold = button_hold

    # -- Private helpers -------------------------------------------------

    def _send_axis(self, address: str, value: float) -> None:
        self._sender.send_float(address, value)

    def _tap(self, address: str) -> None:
        """Send ``1`` -> sleep(``button_hold``) -> ``0``."""
        self._sender.send_bool(address, True)
        if self._button_hold > 0.0:
            time.sleep(self._button_hold)
        self._sender.send_bool(address, False)

    def _hold(self, address: str, active: bool) -> None:
        self._sender.send_bool(address, active)

    # -- Axes (float in [-1.0, 1.0]) ------------------------------------

    def vertical(self, value: float) -> None:
        """Forward/backward locomotion axis (``/input/Vertical``)."""
        self._send_axis("/input/Vertical", value)

    def horizontal(self, value: float) -> None:
        """Strafe axis (``/input/Horizontal``)."""
        self._send_axis("/input/Horizontal", value)

    def look_horizontal(self, value: float) -> None:
        """Continuous yaw axis (``/input/LookHorizontal``)."""
        self._send_axis("/input/LookHorizontal", value)

    def use_axis_right(self, value: float) -> None:
        """Right-hand use axis (``/input/UseAxisRight``)."""
        self._send_axis("/input/UseAxisRight", value)

    def grab_axis_right(self, value: float) -> None:
        """Right-hand grab axis (``/input/GrabAxisRight``)."""
        self._send_axis("/input/GrabAxisRight", value)

    def move_hold_fb(self, value: float) -> None:
        """Held-object forward/back axis (``/input/MoveHoldFB``)."""
        self._send_axis("/input/MoveHoldFB", value)

    def spin_hold_cw_ccw(self, value: float) -> None:
        """Held-object spin CW/CCW axis (``/input/SpinHoldCwCcw``)."""
        self._send_axis("/input/SpinHoldCwCcw", value)

    def spin_hold_ud(self, value: float) -> None:
        """Held-object spin up/down axis (``/input/SpinHoldUD``)."""
        self._send_axis("/input/SpinHoldUD", value)

    def spin_hold_lr(self, value: float) -> None:
        """Held-object spin left/right axis (``/input/SpinHoldLR``)."""
        self._send_axis("/input/SpinHoldLR", value)

    # -- Tap buttons (single-shot) --------------------------------------

    def jump(self) -> None:
        """Tap ``/input/Jump``."""
        self._tap("/input/Jump")

    def voice(self) -> None:
        """Tap ``/input/Voice`` (toggle mode); see :meth:`hold_voice`."""
        self._tap("/input/Voice")

    def panic(self) -> None:
        """Tap ``/input/PanicButton`` (Safety panic)."""
        self._tap("/input/PanicButton")

    def quick_menu_toggle_left(self) -> None:
        """Tap ``/input/QuickMenuToggleLeft``."""
        self._tap("/input/QuickMenuToggleLeft")

    def quick_menu_toggle_right(self) -> None:
        """Tap ``/input/QuickMenuToggleRight``."""
        self._tap("/input/QuickMenuToggleRight")

    def drop_left(self) -> None:
        """Tap ``/input/DropLeft``."""
        self._tap("/input/DropLeft")

    def drop_right(self) -> None:
        """Tap ``/input/DropRight``."""
        self._tap("/input/DropRight")

    def comfort_left(self) -> None:
        """Tap ``/input/ComfortLeft`` (snap-turn left)."""
        self._tap("/input/ComfortLeft")

    def comfort_right(self) -> None:
        """Tap ``/input/ComfortRight`` (snap-turn right)."""
        self._tap("/input/ComfortRight")

    # -- Hold buttons (press/release) -----------------------------------

    def run(self, active: bool = True) -> None:
        """Toggle ``/input/Run`` (sprint) on/off."""
        self._hold("/input/Run", active)

    def hold_voice(self, active: bool = True) -> None:
        """Press/release ``/input/Voice`` for push-to-mute (vs toggle
        :meth:`voice`)."""
        self._hold("/input/Voice", active)

    def move_forward(self, active: bool = True) -> None:
        """Toggle ``/input/MoveForward``."""
        self._hold("/input/MoveForward", active)

    def move_backward(self, active: bool = True) -> None:
        """Toggle ``/input/MoveBackward``."""
        self._hold("/input/MoveBackward", active)

    def move_left(self, active: bool = True) -> None:
        """Toggle ``/input/MoveLeft``."""
        self._hold("/input/MoveLeft", active)

    def move_right(self, active: bool = True) -> None:
        """Toggle ``/input/MoveRight``."""
        self._hold("/input/MoveRight", active)

    def look_left(self, active: bool = True) -> None:
        """Toggle ``/input/LookLeft``."""
        self._hold("/input/LookLeft", active)

    def look_right(self, active: bool = True) -> None:
        """Toggle ``/input/LookRight``."""
        self._hold("/input/LookRight", active)

    def use_left(self, active: bool = True) -> None:
        """Toggle ``/input/UseLeft``."""
        self._hold("/input/UseLeft", active)

    def use_right(self, active: bool = True) -> None:
        """Toggle ``/input/UseRight``."""
        self._hold("/input/UseRight", active)

    def grab_left(self, active: bool = True) -> None:
        """Toggle ``/input/GrabLeft``."""
        self._hold("/input/GrabLeft", active)

    def grab_right(self, active: bool = True) -> None:
        """Toggle ``/input/GrabRight``."""
        self._hold("/input/GrabRight", active)

    # -- Chatbox --------------------------------------------------------

    def chatbox(self, text: str, *, send: bool = True, sfx: bool = True) -> None:
        """Post ``text`` to the in-game chatbox via ``/chatbox/input``.

        ``send=False`` only fills the input field. ``sfx`` toggles the
        notification sound. Text over :data:`CHATBOX_MAX_LENGTH` is
        rejected to mirror VRChat's own limit.
        """
        if len(text) > CHATBOX_MAX_LENGTH:
            raise ValueError(
                f"chatbox text exceeds {CHATBOX_MAX_LENGTH} chars: {len(text)}"
            )
        self._sender.send("/chatbox/input", [str(text), bool(send), bool(sfx)])

    def typing(self, active: bool) -> None:
        """Set the chatbox typing indicator via ``/chatbox/typing``."""
        self._sender.send_bool("/chatbox/typing", active)
