"""OCR engine abstract base class and the :class:`OCRWord` value type.

All coordinates handled here are *image-local* — the origin is the
top-left of the captured image, not the desktop. Callers that need
desktop-absolute coordinates compose them from the engine output and
the originating :class:`~vrcpilot.screenshot.Screenshot`'s
``x`` / ``y`` offsets.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vrcpilot.types import Polygon


@dataclass(frozen=True)
class OCRWord:
    """Single OCR detection in image-local coordinates.

    Attributes:
        text: 認識されたテキスト。
        polygon: 4 頂点 (TL, TR, BR, BL)。傾いたテキストにも対応するため
            一般四角形を許容する。
        confidence: 0.0–1.0 の信頼度。
    """

    text: str
    polygon: Polygon
    confidence: float

    def __post_init__(self) -> None:
        # Static typing pins the length at 4, but downstream callers
        # can construct via ``cast`` or runtime tuple-building, so we
        # guard at construction time too.
        if len(self.polygon) != 4:
            raise ValueError(
                f"OCRWord.polygon must have exactly 4 points; "
                f"got {len(self.polygon)}"
            )

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """Axis-aligned bounding box ``(x, y, width, height)``.

        ``width`` and ``height`` are always non-negative (zero for a
        degenerate polygon).
        """
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        x_min = min(xs)
        x_max = max(xs)
        y_min = min(ys)
        y_max = max(ys)
        return (
            int(round(x_min)),
            int(round(y_min)),
            int(round(x_max - x_min)),
            int(round(y_max - y_min)),
        )

    @property
    def center(self) -> tuple[float, float]:
        """Mean of polygon vertices as ``(x, y)`` floats."""
        mean_x = sum(p[0] for p in self.polygon) / 4
        mean_y = sum(p[1] for p in self.polygon) / 4
        return (float(mean_x), float(mean_y))


class OCREngine(ABC):
    """差し替え可能な OCR バックエンドの抽象基底。

    ユーザーは自前のサブクラスを定義することで rapidocr 以外のエンジン (PaddleOCR、Tesseract、商用 API
    等) を差し込める。
    """

    @abstractmethod
    def recognize(self, image: NDArray[np.uint8]) -> Sequence[OCRWord]:
        """``(H, W, 3)`` uint8 RGB ndarray を受け取り、検出語列を返す。

        Args:
            image: 認識対象の RGB 画像。``np.uint8`` dtype 必須。

        Returns:
            検出された :class:`OCRWord` の列。座標はすべて image-local
            (画像左上原点)。デスクトップ座標への変換は呼び出し側の責務。
        """
