"""High-level :func:`detect` helper and :class:`DetectResult` value type.

Capture and detection are kept separate so the same engine can run
against live screenshots, replayed images, or cropped regions. The
default :class:`TemplateDetectEngine` is built lazily once per process
and cached; tests that need a fresh instance should reset
``_default_engine`` explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vrcpilot.screenshot import Screenshot

from .base import DetectEngine, Detection
from .template import TemplateDetectEngine


@dataclass(frozen=True, eq=False)
class DetectResult:
    """Screenshot + query + detections in image-local coordinates.

    ``eq=False`` because numpy element-wise ``__eq__`` cannot back a
    dataclass equality. ``query`` is stored without copying (engines
    do not mutate it).

    Attributes:
        screenshot: Source screenshot. When the screenshot is a VRChat
            window grab, ``detections`` are also VRChat window-local
            and feed straight into :func:`mouse.move`.
        query: ``(h, w, 3)`` uint8 RGB query passed to the engine.
        detections: Detections in image-local coordinates.
    """

    screenshot: Screenshot
    query: NDArray[np.uint8]
    detections: tuple[Detection, ...]


_default_engine: DetectEngine | None = None


def _get_default_engine() -> DetectEngine:
    """Return a process-cached :class:`TemplateDetectEngine`.

    Not thread-safe; the project runs single-threaded, so the worst case
    under racy access is a transient duplicate engine.
    """
    global _default_engine
    if _default_engine is None:
        _default_engine = TemplateDetectEngine()
    return _default_engine


def detect(
    screenshot: Screenshot,
    query: NDArray[np.uint8],
    *,
    engine: DetectEngine | None = None,
) -> DetectResult:
    """Run *engine* on *screenshot* against *query*.

    The caller owns capture: typically *screenshot* comes from
    :func:`vrcpilot.screenshot.take_screenshot`, but any
    :class:`Screenshot` works. Passing ``engine=None`` reuses the
    process-wide default :class:`TemplateDetectEngine`.
    """
    if engine is None:
        engine = _get_default_engine()
    detections = engine.detect(screenshot.image, query)
    return DetectResult(
        screenshot=screenshot,
        query=query,
        detections=tuple(detections),
    )
