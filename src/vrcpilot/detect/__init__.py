"""Image-query detection of UI elements within VRChat captures.

The public surface is engine-agnostic; :class:`TemplateDetectEngine`
is the default but callers can swap in any :class:`DetectEngine`.

The helper :func:`detect` and this package share a name; the explicit
re-export below wins over the auto-bound submodule, so
``from vrcpilot.detect import detect`` yields the function. Tests that
need to patch internals should reach the submodule via
``sys.modules['vrcpilot.detect.detect']``.
"""

from __future__ import annotations

from vrcpilot.types import Polygon

from .base import DetectEngine, Detection
from .detect import DetectResult, detect
from .template import TemplateDetectEngine
from .visualize import render

__all__ = [
    "DetectEngine",
    "DetectResult",
    "Detection",
    "Polygon",
    "TemplateDetectEngine",
    "detect",
    "render",
]
