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

#: Grace period (seconds) for xclip / xsel to take selection ownership.
#: On Linux, issuing Ctrl+V immediately after copy can land before the
#: selection is published, pasting the *previous* clipboard contents.
_CLIPBOARD_SETTLE: float = 0.05


def paste(text: str, *, focus: bool = True) -> None:
    """Send arbitrary Unicode ``text`` to VRChat via clipboard + Ctrl+V.

    The brief sleep between copy and paste is load-bearing: on Linux,
    xclip / xsel take selection ownership asynchronously, so an
    immediate Ctrl+V can paste the *previous* clipboard contents. Pass
    ``focus=False`` only inside loops that have already verified the
    target window is foreground. Raises
    :class:`pyperclip.PyperclipException` when the clipboard backend
    is missing (e.g. no ``xclip`` / ``xsel`` on Linux).
    """
    pyperclip.copy(text)
    time.sleep(_CLIPBOARD_SETTLE)
    keyboard.press(Key.CTRL, Key.V, focus=focus)
