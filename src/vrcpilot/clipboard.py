"""Clipboard helper for non-ASCII text input into VRChat.

:mod:`vrcpilot.controls.keyboard` is scancode-based and cannot type
non-ASCII characters (e.g. Japanese). This module works around that by
writing the text to the OS clipboard and sending ``Ctrl+V`` to VRChat.
A thin wrapper over a single dependency (``pyperclip``); platform
branching is delegated to pyperclip internally.
"""

from __future__ import annotations

import time

import pyperclip

from vrcpilot.controls import Key, keyboard
from vrcpilot.controls.guard import ensure_target

#: Grace period (seconds) for xclip / xsel to take selection ownership.
#: On Linux, issuing Ctrl+V immediately after copy can land before the
#: selection is published, pasting the *previous* clipboard contents.
_CLIPBOARD_SETTLE: float = 0.05


def paste(text: str, *, focus: bool = True, pid: int | None = None) -> None:
    """Send arbitrary Unicode ``text`` to VRChat via clipboard + Ctrl+V.

    The brief sleep between copy and paste is load-bearing: on Linux,
    xclip / xsel take selection ownership asynchronously, so an
    immediate Ctrl+V can paste the *previous* clipboard contents. Pass
    ``focus=False`` only inside loops that have already verified the
    target window is foreground.

    ``pid`` selects the target VRChat instance when multiple are
    running. The Ctrl+V keystroke is dispatched with ``focus=False`` so
    :func:`ensure_target` runs at most once per call; ``focus=False``
    is the hot-loop fast path and intentionally skips every PID lookup
    (including the internal :func:`vrcpilot.process.resolve_pid`).

    Raises :class:`pyperclip.PyperclipException` when the clipboard
    backend is missing (e.g. no ``xclip`` / ``xsel`` on Linux).
    """
    if focus:
        ensure_target(pid=pid)
    pyperclip.copy(text)
    time.sleep(_CLIPBOARD_SETTLE)
    keyboard.press(Key.CTRL, Key.V, focus=False, pid=pid)
