"""Automation toolkit for VRChat.

Pixel capture is split between :class:`Capture` (focus-free streaming for
video / ML) and :func:`take_screenshot` (one focused shot with on-screen
geometry, for GUI automation). :func:`ocr` consumes a captured
:class:`Screenshot` and runs OCR through a swappable :class:`OCREngine`,
keeping capture and recognition as orthogonal steps.
"""

from importlib import metadata

from vrcpilot import clipboard
from vrcpilot.capture import Capture, CaptureLoop
from vrcpilot.controls import (
    Key,
    MouseButton,
    VRChatNotFocusedError,
    VRChatNotRunningError,
    ensure_target,
    keyboard,
    mouse,
)
from vrcpilot.detect import (
    DetectEngine,
    Detection,
    DetectResult,
    TemplateDetectEngine,
    detect,
)

# Importing ``ocr`` here shadows the ``vrcpilot.ocr`` submodule attribute
# so ``vrcpilot.ocr(shot)`` calls the function; submodule imports still
# resolve via ``sys.modules``. Pinned by ``test_init.py``.
from vrcpilot.ocr import OCREngine, OCRResult, OCRWord, RapidOCREngine, ocr
from vrcpilot.osc import AvatarParameters, InputController, OscSender
from vrcpilot.process import (
    OscConfig,
    find_pid,
    launch,
    terminate,
)
from vrcpilot.screenshot import Screenshot, take_screenshot
from vrcpilot.steam import SteamNotFoundError
from vrcpilot.window import focus, is_foreground, unfocus

#: Resolved from distribution metadata so it stays in sync with
#: ``pyproject.toml`` without being hard-coded here.
__version__ = metadata.version(__name__.replace("_", "-"))

__all__ = [
    "__version__",
    "AvatarParameters",
    "Capture",
    "CaptureLoop",
    "clipboard",
    "detect",
    "DetectEngine",
    "DetectResult",
    "Detection",
    "ensure_target",
    "find_pid",
    "focus",
    "InputController",
    "is_foreground",
    "Key",
    "keyboard",
    "launch",
    "mouse",
    "MouseButton",
    "ocr",
    "OCREngine",
    "OCRResult",
    "OCRWord",
    "OscConfig",
    "OscSender",
    "RapidOCREngine",
    "Screenshot",
    "SteamNotFoundError",
    "take_screenshot",
    "TemplateDetectEngine",
    "terminate",
    "unfocus",
    "VRChatNotFocusedError",
    "VRChatNotRunningError",
]
