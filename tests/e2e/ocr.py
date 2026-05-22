"""E2E scenario: open the VRChat menu and run OCR over it.

Drives the public ``vrcpilot.ocr()`` helper end-to-end against a real
running VRChat client. The default landing screen has very little
on-screen text, so the scenario presses ``Escape`` to bring up the
in-game quick menu (a panel with many labelled buttons) before running
OCR; that gives a stable, text-rich target to verify the pipeline.

Steps:

1. Launch VRChat in Desktop mode (1280x720).
2. Wait for warmup, then ``vrcpilot.keyboard.press(Key.ESCAPE)`` to
   open the menu.
3. ``vrcpilot.take_screenshot()`` grabs the focused VRChat window;
   ``vrcpilot.ocr(shot)`` runs the default ``RapidOCREngine``
   (loads its ONNX models on first call -- downloads ~15 MB to the
   venv on first run) and bundles the words with the screenshot.
4. Verify each :class:`vrcpilot.OCRWord` has a 4-corner polygon, a
   confidence in [0, 1], and a window-local bbox that fits inside the
   captured image.
5. ``vrcpilot.ocr.render`` overlays the boxes on the screenshot so the
   result can be inspected visually.

Run with::

    just e2e-test ocr

Artifacts written to ``_e2e_artifacts/``:

- ``ocr_screenshot_<YYYYMMDD_HHMMSS>.png`` -- the menu screenshot
- ``ocr_viz_<YYYYMMDD_HHMMSS>.png`` -- the same capture with detected
  text boxes drawn over it; open this to verify the boxes look sane
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image

import vrcpilot
from vrcpilot import Key, keyboard
from vrcpilot.ocr import render

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

# Sleep after pressing Escape so the menu animation settles before the
# screenshot is taken. The menu fade-in is well under 1 s in normal play
# but the first time it opens after launch can be slower while shaders
# finish compiling.
_MENU_OPEN_SECONDS: float = 2.0


def _scenario() -> None:
    _helpers.log(
        "calling vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)"
    )
    vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    _helpers.log("pressing Escape to open the in-game menu")
    keyboard.press(Key.ESCAPE)
    time.sleep(_MENU_OPEN_SECONDS)

    _helpers.log("calling take_screenshot() against the menu")
    shot = vrcpilot.take_screenshot()
    assert shot is not None, "take_screenshot() returned None"

    _helpers.log("calling vrcpilot.ocr(shot) (loads OCR models on first run)")
    result = vrcpilot.ocr(shot)
    assert result.screenshot is shot
    _helpers.log(
        "screenshot: "
        f"x={shot.x} y={shot.y} "
        f"width={shot.width} height={shot.height} "
        f"monitor_index={shot.monitor_index}"
    )
    _helpers.log(f"detected {len(result.words)} word(s)")

    # Geometry sanity on the underlying screenshot.
    assert shot.width > 0, f"non-positive width: {shot.width}"
    assert shot.height > 0, f"non-positive height: {shot.height}"
    assert shot.image.shape == (shot.height, shot.width, 3), (
        f"image shape {shot.image.shape} disagrees with "
        f"({shot.height}, {shot.width}, 3)"
    )

    # Per-word invariants. The VRChat menu shows many labelled buttons
    # (Worlds, Avatars, Settings, Logout, etc.); zero detections means
    # either the menu never opened or the OCR pipeline broke.
    assert len(result.words) > 0, (
        "no text detected -- the menu may not have opened or the OCR "
        "pipeline broke; inspect the saved screenshot artifact"
    )
    for i, word in enumerate(result.words):
        assert word.text != "", f"words[{i}] has empty text"
        assert (
            0.0 <= word.confidence <= 1.0
        ), f"words[{i}] confidence {word.confidence} out of [0, 1]"
        assert (
            len(word.polygon) == 4
        ), f"words[{i}] polygon has {len(word.polygon)} corners (expected 4)"
        bx, by, bw, bh = word.bbox
        assert bw > 0 and bh > 0, f"words[{i}] degenerate bbox: {word.bbox}"
        assert (
            0 <= bx < shot.width and 0 <= by < shot.height
        ), f"words[{i}] bbox {word.bbox} outside image"

    # Log the first few detections so the run output is informative
    # without dumping huge YAML for screens with many labels.
    preview_count = min(10, len(result.words))
    _helpers.log(f"first {preview_count} detection(s):")
    for i in range(preview_count):
        word = result.words[i]
        _helpers.log(
            f"  [{i}] text={word.text!r} "
            f"confidence={word.confidence:.3f} "
            f"bbox={word.bbox}"
        )

    raw_path = _helpers.save_image("ocr", "screenshot", Image.fromarray(shot.image))
    _helpers.log(f"raw VRChat screenshot saved: {raw_path}")

    viz = render(result)
    viz_path = _helpers.save_image("ocr", "viz", Image.fromarray(viz))
    _helpers.log(f"OCR visualization saved: {viz_path}")


def main() -> int:
    return _helpers.run_scenario("ocr", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
