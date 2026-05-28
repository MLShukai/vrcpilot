"""E2E scenario: capture a VRChat-only screenshot via ``vrcpilot.take_screenshot()``.

Drives ``vrcpilot.take_screenshot()`` against a real running VRChat
client to confirm that the returned :class:`vrcpilot.Screenshot`
contains **only** the VRChat window region (not the surrounding
desktop, taskbar, or other applications). The pixels now come from
``Capture`` (window-content capture), so the saved PNG is the window's
own framebuffer rather than a cropped desktop region.

VRChat is launched in Desktop mode with a 1280x720 window so the client
is smaller than the screen. That makes the cropping behaviour observable
on inspection: a correct capture shows VRChat content edge-to-edge in
the saved PNG, with no desktop background bleeding in around the
borders.

Run with::

    just e2e-test screenshot

The captured image is written to
``_e2e_artifacts/screenshot/<YYYYMMDD_HHMMSS>/vrchat.png`` for the
human or Claude Code to open and verify. The window geometry and the
captured-at timestamp are also logged.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

import vrcpilot
from vrcpilot.screenshot import take_screenshot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402


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

    _helpers.log("calling take_screenshot()")
    shot = take_screenshot()
    assert shot is not None, "take_screenshot() returned None"

    # ASCII-only log lines: cp932 (Windows + JP locale) cannot encode
    # em-dash / arrow / ellipsis, so any unicode escape leaks here would
    # crash the e2e run.
    _helpers.log(
        "captured: "
        f"x={shot.x} y={shot.y} "
        f"width={shot.width} height={shot.height} "
        f"monitor_index={shot.monitor_index} "
        f"captured_at={shot.captured_at.isoformat()}"
    )
    _helpers.log(f"image: shape={shot.image.shape} dtype={shot.image.dtype}")

    # Geometry sanity. ``x`` / ``y`` may be negative on multi-monitor
    # layouts where VRChat is on a left-of-primary monitor, so do not
    # constrain their sign — only the size and monitor index are
    # universally non-negative.
    assert shot.width > 0, f"non-positive width: {shot.width}"
    assert shot.height > 0, f"non-positive height: {shot.height}"
    assert shot.monitor_index >= 0, f"negative monitor index: {shot.monitor_index}"
    assert shot.image.shape == (shot.height, shot.width, 3), (
        f"image shape {shot.image.shape} disagrees with "
        f"({shot.height}, {shot.width}, 3)"
    )
    assert shot.image.dtype.name == "uint8", f"unexpected dtype: {shot.image.dtype}"

    out = _helpers.save_image("screenshot", "vrchat", Image.fromarray(shot.image))
    _helpers.log(f"VRChat screenshot saved: {out}")


def main() -> int:
    return _helpers.run_scenario("screenshot", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
