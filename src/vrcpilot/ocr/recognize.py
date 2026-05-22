"""High-level :func:`ocr` helper and the :class:`OCRResult` value type.

:class:`OCRResult` ties a :class:`Screenshot` to the
:class:`OCRWord` list produced by an :class:`OCREngine`. All
coordinates exposed by :class:`OCRWord` are window-local (origin =
``screenshot`` top-left).

:func:`ocr` is a thin pure-OCR step: the caller supplies the
:class:`Screenshot` (typically from
:func:`vrcpilot.screenshot.take_screenshot`), and this function only
runs the engine and packages the result. Capture and OCR are kept as
separate concerns so the same OCR pipeline can be replayed against
existing images, fed cropped regions, or driven by a custom capture
source.

The module-level ``_default_engine`` cache keeps :func:`ocr` cheap on
repeat calls: the (heavy) :class:`RapidOCREngine` is built exactly
once per process when the user does not pass an ``engine`` argument.
Tests that need a fresh cache should reset the variable explicitly
(``vrcpilot.ocr.recognize._default_engine = None``).
"""

from __future__ import annotations

from dataclasses import dataclass

from vrcpilot.screenshot import Screenshot

from .base import OCREngine, OCRWord
from .rapidocr import RapidOCREngine


@dataclass(frozen=True, eq=False)
class OCRResult:
    """Captured screenshot bundled with its OCR detections.

    ``eq=False`` mirrors :class:`vrcpilot.screenshot.Screenshot`:
    ``screenshot.image`` is a numpy ``ndarray`` and element-wise
    ``__eq__`` cannot back the dataclass-synthesised equality.

    Attributes:
        screenshot: The :class:`Screenshot` the words were extracted
            from.
        words: Detected :class:`OCRWord` tuple. All word coordinates
            (``polygon`` / ``bbox``) are window-local (origin =
            ``screenshot`` top-left). Always a ``tuple`` so the
            sequence is immutable from the caller's point of view
            (matches the frozen-dataclass posture of :class:`OCRWord`).
    """

    screenshot: Screenshot
    words: tuple[OCRWord, ...]


_default_engine: OCREngine | None = None


def _get_default_engine() -> OCREngine:
    """Return the cached default :class:`OCREngine`, building it if needed.

    The first call constructs a :class:`RapidOCREngine`; subsequent
    calls reuse the cached instance. Not thread-safe — the project
    runs in a single context, so the worst case under racy access is
    a transient duplicate engine that is immediately replaced.
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

    The caller is responsible for capture; pass any
    :class:`Screenshot` (typically from
    :func:`vrcpilot.screenshot.take_screenshot`, but a hand-built one
    or a replayed capture works just as well).

    Args:
        screenshot: Image to recognise. ``screenshot.image`` is fed
            to the engine and the :class:`Screenshot` is preserved on
            the returned :class:`OCRResult` so callers retain access
            to ``screenshot.x`` / ``y`` (window-on-desktop offsets)
            when they need them.
        engine: OCR backend. ``None`` (default) lazily builds and
            caches a :class:`RapidOCREngine` via
            :func:`_get_default_engine`.

    Returns:
        :class:`OCRResult` pairing *screenshot* with the detected
        words (possibly empty). Never returns ``None``.
    """
    if engine is None:
        engine = _get_default_engine()
    words = engine.recognize(screenshot.image)
    return OCRResult(screenshot=screenshot, words=tuple(words))
