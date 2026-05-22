"""High-level :func:`detect` helper and :class:`DetectResult` value type.

Capture and detection are decoupled so the same engine can run against
live screenshots, replays, or crops. The default engine is built lazily
and cached per process; tests needing isolation reset ``_default_engine``.
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

    When ``screenshot`` is a VRChat window grab, detection coordinates
    are VRChat window-local and feed straight into :func:`mouse.move`.
    ``eq=False`` because numpy element-wise equality cannot back a
    dataclass; ``query`` is stored by reference (engines do not mutate).
    """

    screenshot: Screenshot
    query: NDArray[np.uint8]
    detections: tuple[Detection, ...]


_default_engine: DetectEngine | None = None


def _get_default_engine() -> DetectEngine:
    """Return a process-cached :class:`TemplateDetectEngine`.

    Not thread-safe by design: the project runs single-threaded and a
    racy duplicate engine would be harmless.
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

    The caller owns capture; any :class:`Screenshot` works. Passing
    ``engine=None`` reuses the process-wide default
    :class:`TemplateDetectEngine`.
    """
    if engine is None:
        engine = _get_default_engine()
    detections = engine.detect(screenshot.image, query)
    return DetectResult(
        screenshot=screenshot,
        query=query,
        detections=tuple(detections),
    )
