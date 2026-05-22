"""OCR primitives for VRChat screen analysis.

Public surface:

* :class:`OCREngine` — swappable backend ABC.
* :class:`OCRWord` — single-detection value type. Coordinates are
  window-local (origin = screenshot top-left), so callers can pass
  them straight to :func:`vrcpilot.controls.mouse.move`.
* :class:`OCRResult` — screenshot + word tuple.
* :class:`RapidOCREngine` — default rapidocr-backed engine.
* :func:`ocr` — runs an :class:`OCREngine` on a captured
  :class:`Screenshot` and bundles the words with it.
* :func:`render` — draws an :class:`OCRResult` onto an ndarray
  suitable for ``PIL.Image.fromarray``.
* :data:`Polygon` — the 4-corner polygon type alias used across the
  module; re-exported here so users implementing their own
  :class:`OCREngine` can annotate against the same shape.

Note on the ``ocr`` name: the helper function and the package share
the name. ``from vrcpilot.ocr import ocr`` returns the function (the
explicit re-export below wins over the auto-bound submodule). Tests
that need to monkey-patch internals on the ``recognize`` submodule
should reach it via ``sys.modules['vrcpilot.ocr.recognize']`` to
bypass attribute resolution.
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
