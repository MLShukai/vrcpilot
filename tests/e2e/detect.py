"""E2E scenario: detect Launch Pad icons in a real VRChat window.

Opens the Launch Pad (Escape), screenshots it, then runs
:func:`vrcpilot.detect.detect` for every PNG under
``tests/e2e/fixtures/detect_icons/``. Fails if any icon goes
undetected; artifacts land under
``_e2e_artifacts/detect/<YYYYMMDD_HHMMSS>/``.

Run with::

    just e2e-test detect
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

import vrcpilot
from vrcpilot import Key, keyboard
from vrcpilot.detect import Detection, detect

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

_MENU_OPEN_SECONDS: float = 2.0
_ICONS_DIR: Path = Path(__file__).resolve().parent / "fixtures" / "detect_icons"


def _load_query(path: Path) -> NDArray[np.uint8]:
    """Read *path* as RGB ``uint8`` ndarray; raises on failure."""
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"could not read query image: {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return np.asarray(rgb, dtype=np.uint8)


def _draw_combined_viz(
    image: NDArray[np.uint8],
    detections_by_query: dict[str, tuple[Detection, ...]],
) -> NDArray[np.uint8]:
    """Overlay every query's detections onto a single copy of *image*."""
    canvas: NDArray[np.uint8] = image.copy()
    for name, detections in detections_by_query.items():
        for det in detections:
            polygon_pts = np.array(det.polygon, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(
                canvas,
                [polygon_pts],
                isClosed=True,
                color=(0, 255, 0),
                thickness=2,
            )
            bx, by, _bw, bh = det.bbox
            label = f"{name} {det.confidence:.2f}"
            (_text_w, text_h), _baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            text_y = by - 4 if by - text_h - 4 >= 0 else by + bh + text_h + 4
            cv2.putText(
                canvas,
                label,
                (bx, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
    return canvas


def _scenario() -> None:
    queries = sorted(p for p in _ICONS_DIR.glob("*.png"))
    if not queries:
        raise RuntimeError(
            f"no query PNGs found under {_ICONS_DIR}; "
            "populate the directory before running this scenario"
        )
    _helpers.log(f"loaded {len(queries)} query icon(s) from {_ICONS_DIR}")

    _helpers.log(
        "calling vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)"
    )
    vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    _helpers.log("pressing Escape to open the Launch Pad")
    keyboard.press(Key.ESCAPE)
    time.sleep(_MENU_OPEN_SECONDS)

    _helpers.log("calling take_screenshot() against the Launch Pad")
    shot = vrcpilot.take_screenshot()
    assert shot is not None, "take_screenshot() returned None"
    _helpers.log(
        "screenshot: "
        f"x={shot.x} y={shot.y} "
        f"width={shot.width} height={shot.height} "
        f"monitor_index={shot.monitor_index}"
    )

    raw_path = _helpers.save_image("detect", "screenshot", Image.fromarray(shot.image))
    _helpers.log(f"raw VRChat screenshot saved: {raw_path}")

    detections_by_query: dict[str, tuple[Detection, ...]] = {}
    failures: list[str] = []
    for query_path in queries:
        name = query_path.stem
        query = _load_query(query_path)
        qh, qw = query.shape[:2]
        _helpers.log(f"detecting {name}.png (query={qw}x{qh})")
        result = detect(shot, query)
        detections_by_query[name] = result.detections

        if not result.detections:
            _helpers.log(f"  FAIL {name}: no detections")
            failures.append(name)
            continue

        for i, det in enumerate(result.detections):
            cx, cy = det.center
            assert (
                0 <= cx <= shot.width
            ), f"{name}[{i}] center.x={cx} outside [0, {shot.width}]"
            assert (
                0 <= cy <= shot.height
            ), f"{name}[{i}] center.y={cy} outside [0, {shot.height}]"
            assert (
                0.0 <= det.confidence <= 1.0
            ), f"{name}[{i}] confidence {det.confidence} out of [0, 1]"
            assert (
                len(det.polygon) == 4
            ), f"{name}[{i}] polygon has {len(det.polygon)} corners (expected 4)"

        first = result.detections[0]
        _helpers.log(
            f"  OK   {name}: {len(result.detections)} hit(s), "
            f"top center={first.center} "
            f"confidence={first.confidence:.3f} "
            f"scale={first.scale:.3f} "
            f"rotation={first.rotation:.3f}"
        )

    viz = _draw_combined_viz(shot.image, detections_by_query)
    viz_path = _helpers.save_image("detect", "viz", Image.fromarray(viz))
    _helpers.log(f"combined viz saved: {viz_path}")

    if failures:
        raise AssertionError(
            f"{len(failures)}/{len(queries)} query icons not detected: "
            f"{', '.join(failures)} -- inspect {viz_path}"
        )
    _helpers.log(f"all {len(queries)} query icons detected")


def main() -> int:
    return _helpers.run_scenario("detect", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
