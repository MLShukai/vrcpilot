"""High-level :func:`ocr` helper and the :class:`OCRResult` value type.

Capture and OCR are kept separate: the caller passes a
:class:`Screenshot` (usually from
:func:`vrcpilot.screenshot.take_screenshot`, but any source works) and
this module just runs the engine. All resulting :class:`OCRWord`
coordinates are window-local (origin = ``screenshot`` top-left).

The default :class:`RapidOCREngine` is heavy, so it is built once per
process and cached in ``_default_engine``. Tests that need a fresh
cache must reset it explicitly:
``vrcpilot.ocr.recognize._default_engine = None``.
"""

from __future__ import annotations

from dataclasses import dataclass

from vrcpilot.screenshot import Screenshot

from .base import OCREngine, OCRWord
from .rapidocr import RapidOCREngine


@dataclass(frozen=True, eq=False)
class OCRResult:
    """Captured screenshot bundled with its OCR detections.

    ``words`` coordinates are window-local (origin = ``screenshot``
    top-left); ``words`` is a tuple to keep the sequence immutable in
    line with :class:`OCRWord`'s frozen-dataclass posture. ``eq=False``
    mirrors :class:`vrcpilot.screenshot.Screenshot`: the underlying
    ndarray cannot back the dataclass-synthesized ``__eq__``.
    """

    screenshot: Screenshot
    words: tuple[OCRWord, ...]


_default_engine: OCREngine | None = None


def _get_default_engine() -> OCREngine:
    """Return the process-wide cached :class:`RapidOCREngine`, building it
    lazily.

    Not thread-safe; under racy access the worst case is a transient
    duplicate engine that is immediately replaced.
    """
    global _default_engine
    if _default_engine is None:
        _default_engine = RapidOCREngine()
    return _default_engine


def ocr(
    screenshot: Screenshot,
    *,
    engine: OCREngine | None = None,
) -> OCRResult:
    """Run OCR on *screenshot* and bundle the words with it.

    Capture is the caller's job — pass any :class:`Screenshot` (live
    capture, hand-built, or replayed). The original
    :class:`Screenshot` is preserved on the result so capture metadata
    (``captured_at``, ``x`` / ``y`` offsets) survives the round trip.
    ``engine=None`` reuses the cached default :class:`RapidOCREngine`.
    """
    if engine is None:
        engine = _get_default_engine()
    words = engine.recognize(screenshot.image)
    return OCRResult(screenshot=screenshot, words=tuple(words))
