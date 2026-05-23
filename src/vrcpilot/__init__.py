"""Automation toolkit for VRChat.

Pixel capture is split between :class:`Capture` (focus-free streaming for
video / ML) and :func:`take_screenshot` (one focused shot with on-screen
geometry, for GUI automation). :func:`ocr` consumes a captured
:class:`Screenshot` and runs OCR through a swappable :class:`OCREngine`,
keeping capture and recognition as orthogonal steps.
"""

import sys

if sys.platform not in ("win32", "linux"):
    raise ImportError(
        f"vrcpilot supports only Windows and Linux "
        f"(got sys.platform={sys.platform!r})"
    )

from importlib import metadata

from vrcpilot import clipboard
from vrcpilot.capture import Capture, CaptureLoop
from vrcpilot.controls import (
    Key,
    MouseButton,
    VRChatNotFocusedError,
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
from vrcpilot.mic import Mic, MicDeviceNotFoundError

# Importing ``ocr`` here shadows the ``vrcpilot.ocr`` submodule attribute
# so ``vrcpilot.ocr(shot)`` calls the function; submodule imports still
# resolve via ``sys.modules``. Pinned by ``test_init.py``.
from vrcpilot.ocr import OCREngine, OCRResult, OCRWord, RapidOCREngine, ocr
from vrcpilot.osc import AvatarParameters, InputController, OscSender
from vrcpilot.process import (
    OscConfig,
    UmuLauncherNotFoundError,
    VRChatAlreadyRunningError,
    VRChatLauncherNotFoundError,
    VRChatMultipleInstancesError,
    VRChatNotRunningError,
    find_pid,
    find_pids,
    launch,
    resolve_pid,
    terminate,
)

# ``find_vrchat_launcher`` / ``find_umu_launcher`` live in the private
# ``vrcpilot.process._executable`` module but the functions themselves
# are part of the public API. Importing them directly avoids touching
# ``process/__init__.py`` while parallel work (C8) is modifying it.
# Future cleanup: once C8 lands, re-route through
# ``vrcpilot.process.find_vrchat_launcher`` for symmetry with the
# other process helpers.
from vrcpilot.process._executable import (  # noqa: PLC2701
    find_umu_launcher,
    find_vrchat_launcher,
)
from vrcpilot.screenshot import Screenshot, take_screenshot
from vrcpilot.speaker import AudioCallback, Speaker, SpeakerLoop
from vrcpilot.steam import SteamNotFoundError
from vrcpilot.window import focus, is_foreground, unfocus

#: Resolved from distribution metadata so it stays in sync with
#: ``pyproject.toml`` without being hard-coded here.
__version__ = metadata.version(__name__.replace("_", "-"))

__all__ = [
    "__version__",
    "AudioCallback",
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
    "find_pids",
    "find_umu_launcher",
    "find_vrchat_launcher",
    "focus",
    "InputController",
    "is_foreground",
    "Key",
    "keyboard",
    "launch",
    "Mic",
    "MicDeviceNotFoundError",
    "mouse",
    "MouseButton",
    "ocr",
    "OCREngine",
    "OCRResult",
    "OCRWord",
    "OscConfig",
    "OscSender",
    "RapidOCREngine",
    "resolve_pid",
    "Screenshot",
    "Speaker",
    "SpeakerLoop",
    "SteamNotFoundError",
    "take_screenshot",
    "TemplateDetectEngine",
    "terminate",
    "UmuLauncherNotFoundError",
    "unfocus",
    "VRChatAlreadyRunningError",
    "VRChatLauncherNotFoundError",
    "VRChatMultipleInstancesError",
    "VRChatNotFocusedError",
    "VRChatNotRunningError",
]
