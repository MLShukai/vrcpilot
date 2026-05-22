"""Rapidocr-backed :class:`OCREngine` implementation.

``rapidocr`` is imported inside the constructor, not at module load,
so ``from vrcpilot.ocr import OCREngine`` continues to work when the
``[ocr]`` extra is not installed.
"""

from __future__ import annotations

from typing import Any, override

import numpy as np
from numpy.typing import NDArray

from vrcpilot.types import Polygon

from .base import OCREngine, OCRWord


class RapidOCREngine(OCREngine):
    """Default :class:`OCREngine` backed by rapidocr (PP-OCRv4).

    Instantiation triggers the lazy ``import rapidocr``; without the
    ``[ocr]`` extra installed this raises :class:`ImportError`.
    """

    def __init__(self, *, params: dict[str, Any] | None = None) -> None:
        """Build the underlying rapidocr engine.

        ``params`` is forwarded verbatim to ``RapidOCR(params=...)``;
        ``None`` uses the rapidocr default (PP-OCRv4). Raises
        :class:`ImportError` when ``rapidocr`` is not installed — install
        with ``pip install vrcpilot[ocr]``.
        """
        try:
            # ``rapidocr`` ships no type stubs; suppress the import-time
            # warning here, then assign the constructed engine to a
            # ``self._engine: Any`` slot so the rest of this class never
            # has to repeat the ignore.
            from rapidocr import RapidOCR  # pyright: ignore[reportMissingTypeStubs]
        except ImportError as e:
            raise ImportError(
                "rapidocr is required for RapidOCREngine. "
                "Install with: pip install vrcpilot[ocr]"
            ) from e

        # rapidocr 自体に型 stub が無いため Any で受ける
        self._engine: Any = RapidOCR(params=params)

    @override
    def recognize(self, image: NDArray[np.uint8]) -> list[OCRWord]:
        """Run rapidocr on an ``(H, W, 3)`` uint8 RGB image.

        No BGR conversion is needed: rapidocr 3.x consumes RGB ndarrays
        directly. Returns an empty list when nothing is detected.
        """
        result: Any = self._engine(image)

        # rapidocr v3.x: 検出ゼロのとき .boxes / .txts / .scores が
        # それぞれ None になる。3 つすべて存在するときのみ語を構築。
        boxes: Any = getattr(result, "boxes", None)
        txts: Any = getattr(result, "txts", None)
        scores: Any = getattr(result, "scores", None)
        if boxes is None or txts is None or scores is None:
            return []

        words: list[OCRWord] = []
        # 3 配列の長さは rapidocr 仕様上揃うが、防御的に min を取る
        n = min(len(boxes), len(txts), len(scores))
        for i in range(n):
            box = boxes[i]
            polygon: Polygon = (
                (float(box[0][0]), float(box[0][1])),
                (float(box[1][0]), float(box[1][1])),
                (float(box[2][0]), float(box[2][1])),
                (float(box[3][0]), float(box[3][1])),
            )
            words.append(
                OCRWord(
                    text=str(txts[i]),
                    polygon=polygon,
                    confidence=float(scores[i]),
                )
            )
        return words
