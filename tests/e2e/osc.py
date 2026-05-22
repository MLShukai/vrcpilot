"""E2E scenario: drive VRChat's OSC Debug Panel as a visual oracle.

The previous version of this scenario merely dumped desktop PNGs
between sends, which proved nothing: in the default world, ``jump()``,
locomotion and avatar parameter writes have no on-screen effect, so
the artifacts could not distinguish a working OSC pipeline from a
silently broken one. The fix is to enable VRChat's built-in OSC Debug
Panel and float it as a "trinket" -- a panel pinned to the world that
survives menu dismissal. Every received OSC address then appears as a
new line on that panel, turning each per-step screenshot into a
visible oracle that a human reviewer can verify.

Run with::

    just e2e-test osc
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
from vrcpilot import Key, Screenshot, clipboard, keyboard, mouse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

# Use a non-default port to avoid colliding with another OSC tool the
# user may already have bound to 9000.
_OSC_IN_PORT = 9100

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "open_osc_debug"


def _load_query(path: Path) -> NDArray[np.uint8]:
    """Read *path* as RGB ``uint8`` ndarray; mirrors
    ``tests/e2e/detect.py``."""
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"could not read query image: {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return np.asarray(rgb, dtype=np.uint8)


def _shot(label: str) -> Screenshot:
    """Take + assert + ``save_image`` collapsed into one call site."""
    shot = vrcpilot.take_screenshot()
    assert shot is not None, f"take_screenshot() returned None at {label!r}"
    path = _helpers.save_image("osc", label, Image.fromarray(shot.image))
    _helpers.log(f"  shot {label} saved: {path}")
    return shot


def _open_osc_debug_panel() -> None:
    """Drive VRChat's UI until the OSC Debug Panel is floating as a trinket.

    The toggle that floats the panel lives deep inside VRChat's
    settings UI and there is no API or launch flag to flip it -- the
    only path is to navigate the real UI. The Search field is used
    because the settings list is long enough that the OSC Debug Panel
    row is rarely visible in the initial settings viewport. The final
    ``Esc`` is intentional: closing the menu leaves the panel pinned
    to the world (the "Floating Trinket" behaviour), which is exactly
    the state subsequent OSC sends rely on for visual feedback.

    Steps: 1) Esc -> Launch Pad. 2) Template-detect the gear icon and
    double-click into full settings. 3) OCR for "Search all settings"
    and click it. 4) Paste "OSC" + Enter. 5) OCR for "OSC Debug Panel"
    to anchor the row. 6) Template-detect off-toggles and click the
    one on the panel's row. 7) Esc to drop the menu, leaving the panel
    floating. Failures surface as ``AssertionError`` with the offending
    artifact already saved -- same failure model as the other e2e
    scenarios.
    """
    _helpers.log("Esc -> Launch Pad")
    keyboard.press(Key.ESCAPE)
    # 2.0s matches tests/e2e/detect.py: enough headroom for the
    # Launch Pad fade-in even on first-launch shader compilation.
    time.sleep(2.0)

    shot = _shot("01_launchpad")
    config_query = _load_query(_FIXTURE_DIR / "config.png")
    config_result = vrcpilot.detect(shot, config_query)
    assert config_result.detections, (
        "config (gear) icon not detected on Launch Pad; "
        "see saved 01_launchpad artifact"
    )
    gear = config_result.detections[0]
    gx, gy, gw, gh = config_result.display_bbox(gear)
    gear_cx = gx + gw // 2
    gear_cy = gy + gh // 2
    _helpers.log(f"gear icon -> click ({gear_cx}, {gear_cy})")
    mouse.move(gear_cx, gear_cy)
    # A real double-click (press-release-press-release with no
    # inter-cycle delay) is required: a single click only opens the
    # Quick Menu Settings panel, while VRChat treats the second click
    # as a *double-click* gesture to expand into the full settings
    # screen that hosts the search field. Two click() calls separated
    # by sleep(0.4) registered as two separate single-clicks and never
    # triggered the expansion -- count=2 collapses them into one
    # double-click event.
    mouse.click(count=2, duration=0.05)
    time.sleep(1.5)

    shot = _shot("02_settings")
    ocr_result = vrcpilot.ocr(shot)
    search_word = None
    for word in ocr_result.words:
        t = word.text.lower()
        if "search" in t and "settings" in t:
            search_word = word
            break
    assert search_word is not None, (
        "'Search all settings' field not found via OCR; "
        "see saved 02_settings artifact"
    )
    sbx, sby, sw, sh = search_word.bbox
    search_cx = shot.x + sbx + sw // 2
    search_cy = shot.y + sby + sh // 2
    _helpers.log(f"search field -> click ({search_cx}, {search_cy})")
    mouse.move(search_cx, search_cy)
    mouse.click()
    time.sleep(0.5)

    _helpers.log('paste "OSC" + Enter')
    clipboard.paste("OSC")
    time.sleep(0.3)
    keyboard.press(Key.ENTER)
    # 1.0s for the search filter to repaint -- earlier reads catch the
    # unfiltered list and the OCR below misses "OSC Debug Panel".
    time.sleep(1.0)

    shot = _shot("03_searched")
    ocr_result = vrcpilot.ocr(shot)
    panel_word = None
    for word in ocr_result.words:
        if word.text.lower().replace(" ", "") == "oscdebugpanel":
            panel_word = word
            break
    assert panel_word is not None, (
        "'OSC Debug Panel' label not found via OCR after search; "
        "see saved 03_searched artifact"
    )
    # Use the bbox *center* y, not its top edge: the OCR word height
    # tracks the label glyphs and the toggle icon on the same row is
    # vertically aligned to that midline. Top-edge y would bias the
    # row match toward whichever toggle sits highest in its row.
    _pbx, pby, _pw, ph = panel_word.bbox
    panel_y = shot.y + pby + ph // 2

    toggle_query = _load_query(_FIXTURE_DIR / "toggle_off.png")
    toggle_result = vrcpilot.detect(shot, toggle_query)
    assert toggle_result.detections, (
        "no off-toggles detected on the searched settings screen; "
        "see saved 03_searched artifact"
    )

    # Filtered "OSC" results still contain several rows (Debug Panel,
    # Self Receive, etc.) each with its own toggle, so picking the
    # highest-confidence detection is wrong -- match the toggle whose
    # row center is closest to the OSC Debug Panel label.
    def _row_distance(det: vrcpilot.Detection) -> int:
        _tx, ty, _tw, th = toggle_result.display_bbox(det)
        return abs((ty + th // 2) - panel_y)

    toggle = min(toggle_result.detections, key=_row_distance)
    tx, ty, tw, th = toggle_result.display_bbox(toggle)
    toggle_cx = tx + tw // 2
    toggle_cy = ty + th // 2
    _helpers.log(
        f"OSC Debug Panel row y={panel_y}, "
        f"toggle -> click ({toggle_cx}, {toggle_cy})"
    )
    mouse.move(toggle_cx, toggle_cy)
    mouse.click()
    time.sleep(0.8)

    _shot("04_toggled")

    # Closing the menu intentionally: the OSC Debug Panel stays pinned
    # to the world as a floating trinket once the surrounding menu is
    # dismissed -- that pinned state is what later sends rely on.
    _helpers.log("Esc -> close menu, panel should remain floating")
    keyboard.press(Key.ESCAPE)
    time.sleep(1.0)

    _shot("05_panel_floating")


def _scenario() -> None:
    """Send across every ``OscSender`` surface and screenshot the panel each
    time.

    The actual oracle is the resulting per-step PNG: each send must
    appear as a fresh line on the floating OSC Debug Panel. The
    in-process assertions only confirm the calls did not raise.
    """
    _helpers.log(f"calling vrcpilot.launch(no_vr=True, osc=in_port={_OSC_IN_PORT})")
    vrcpilot.launch(no_vr=True, osc=vrcpilot.OscConfig(in_port=_OSC_IN_PORT))

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    _open_osc_debug_panel()

    sender = vrcpilot.OscSender(port=_OSC_IN_PORT)
    ctrl = sender.controller()
    avatars = sender.avatar_parameters()

    _helpers.log("chatbox: send a message")
    ctrl.chatbox("vrcpilot OSC e2e", send=True, sfx=False)
    time.sleep(0.6)
    _shot("10_chatbox")

    _helpers.log("tap: jump()")
    ctrl.jump()
    time.sleep(0.6)
    _shot("11_jump")

    _helpers.log("movement: run + vertical(1.0) for ~0.8s")
    ctrl.run(True)
    ctrl.vertical(1.0)
    time.sleep(0.8)
    ctrl.vertical(0.0)
    ctrl.run(False)
    time.sleep(0.4)
    _shot("12_move")

    # Avatar parameter writes are smoke tests only. VRChat silently
    # ignores parameters the active avatar does not declare, so we use
    # synthetic names; the OSC Debug Panel still records each write.
    _helpers.log("avatar parameter: bool")
    avatars.send_bool("vrcpilot_test_bool", True)
    time.sleep(0.3)
    _shot("13_avatar_bool")

    _helpers.log("avatar parameter: int")
    avatars.send_int("vrcpilot_test_int", 1)
    time.sleep(0.3)
    _shot("14_avatar_int")

    _helpers.log("avatar parameter: float")
    avatars.send_float("vrcpilot_test_float", 0.5)
    time.sleep(0.3)
    _shot("15_avatar_float")

    _helpers.log("raw send: /avatar/parameters/vrcpilot_test_raw = 42")
    sender.send("/avatar/parameters/vrcpilot_test_raw", 42)
    time.sleep(0.3)
    _shot("16_raw")

    _helpers.log("OSC e2e: all commands sent without exceptions")


def main() -> int:
    return _helpers.run_scenario("osc", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
