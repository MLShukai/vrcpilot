"""OCR primitives for VRChat screen analysis.

All :class:`OCRWord` coordinates are window-local (origin = screenshot
top-left), so they can be passed straight to
:func:`vrcpilot.controls.mouse.move` without translation.

The helper :func:`ocr` and this package share a name; the explicit
re-export below wins over the auto-bound submodule, so
``from vrcpilot.ocr import ocr`` yields the function. Tests that need
to patch internals should reach the submodule via
``sys.modules['vrcpilot.ocr.recognize']``.
"""

from __future__ import annotations

from vrcpilot.types import Polygon

from .base import OCREngine, OCRWord
from .rapidocr import RapidOCREngine
from .recognize import OCRResult, ocr
from .visualize import render

__all__ = [
    "OCREngine",
    "OCRResult",
    "OCRWord",
    "Polygon",
    "RapidOCREngine",
    "ocr",
    "render",
]
