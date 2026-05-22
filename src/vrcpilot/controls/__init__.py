"""VRChat-targeted synthetic mouse and keyboard input.

Every public input call runs :func:`ensure_target` first by default;
pass ``focus=False`` inside hot loops that have already verified focus.
Native Wayland is rejected up front (XWayland is fine).

Variadic combos (``press`` / ``down`` / ``up`` / ``click`` / ``release``)
go down left-to-right and come up in reverse, so modifiers outlive the
keys they modify (the standard Ctrl+C convention).

Usage::

    import vrcpilot
    vrcpilot.mouse.click()
    vrcpilot.keyboard.press(vrcpilot.Key.CTRL, vrcpilot.Key.C)
"""

from . import keyboard, mouse
from .errors import VRChatNotFocusedError, VRChatNotRunningError
from .guard import ensure_target
from .keyboard import Key
from .mouse import MouseButton

__all__ = [
    "ensure_target",
    "Key",
    "keyboard",
    "mouse",
    "MouseButton",
    "VRChatNotFocusedError",
    "VRChatNotRunningError",
]
