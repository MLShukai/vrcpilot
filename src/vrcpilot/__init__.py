"""Automation toolkit for VRChat.

Pixel capture is split between :class:`vrcpilot.capture.Capture` (focus-
free streaming for video / ML) and :func:`take_screenshot` (one focused
shot with on-screen geometry, for GUI automation). :func:`ocr` consumes
a captured :class:`Screenshot` and runs OCR through a swappable
:class:`vrcpilot.ocr.OCREngine`, keeping capture and recognition as
orthogonal steps.
"""

import sys

if sys.platform not in ("win32", "linux"):
    raise ImportError(
        f"vrcpilot supports only Windows and Linux "
        f"(got sys.platform={sys.platform!r})"
    )

from importlib import metadata

from vrcpilot import clipboard
from vrcpilot.capture import CaptureLoop
from vrcpilot.controls import (
    Key,
    MouseButton,
    VRChatNotFocusedError,
    keyboard,
    mouse,
)
from vrcpilot.detect import detect
from vrcpilot.mic import Mic, MicDeviceNotFoundError

# Importing ``ocr`` here shadows the ``vrcpilot.ocr`` submodule attribute
# so ``vrcpilot.ocr(shot)`` calls the function; submodule imports still
# resolve via ``sys.modules``. Pinned by ``test_init.py``.
from vrcpilot.ocr import ocr
from vrcpilot.osc import OscSender
from vrcpilot.process import (
    OscConfig,
    VRChatMultipleInstancesError,
    VRChatNotRunningError,
    find_pid,
    find_pids,
    launch,
    terminate,
)
from vrcpilot.screenshot import Screenshot, take_screenshot
from vrcpilot.steam import SteamNotFoundError
from vrcpilot.window import focus, is_foreground, unfocus

#: Resolved from distribution metadata so it stays in sync with
#: ``pyproject.toml`` without being hard-coded here.
__version__ = metadata.version(__name__.replace("_", "-"))

#: Top-level namespace is intentionally narrow: only user-facing entry
#: points live here. Implementation classes, ABCs, engine backends, and
#: internal helpers stay on their subpackages
#: (``vrcpilot.capture.Capture``, ``vrcpilot.ocr.OCREngine``,
#: ``vrcpilot.osc.InputController``, ``vrcpilot.process.resolve_pid``,
#: etc.). Pinned by ``tests/vrcpilot/test_init.py``.
__all__ = [
    "__version__",
    "CaptureLoop",
    "clipboard",
    "detect",
    "find_pid",
    "find_pids",
    "focus",
    "is_foreground",
    "Key",
    "keyboard",
    "launch",
    "Mic",
    "MicDeviceNotFoundError",
    "mouse",
    "MouseButton",
    "ocr",
    "OscConfig",
    "OscSender",
    "Screenshot",
    "SteamNotFoundError",
    "take_screenshot",
    "terminate",
    "unfocus",
    "VRChatMultipleInstancesError",
    "VRChatNotFocusedError",
    "VRChatNotRunningError",
]
