"""E2E scenario: launch VRChat in Desktop mode and verify focus/unfocus.

Drives ``vrcpilot.focus()`` and ``vrcpilot.unfocus()`` against a real
running VRChat client to confirm that the window can be brought to the
foreground and sent to the bottom of the z-order.

The operations are interleaved as ``unfocus -> focus -> unfocus -> focus``
so each call causes an observable state change. Right after launch
VRChat is naturally in the foreground, so calling ``focus()`` first
would not prove anything; starting with ``unfocus()`` makes the very
first transition meaningful, and repeating the pair verifies the calls
are idempotent. A screenshot is saved after each step under
``_e2e_artifacts/focus_unfocus/<YYYYMMDD_HHMMSS>/<step>.png`` (e.g.
``1_unfocus.png``) for visual inspection.

Run with::

    just e2e-test focus_unfocus

VRChat is launched with ``no_vr=True`` (Desktop mode) so the focus /
unfocus effects are observable without an HMD.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import vrcpilot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402


def _scenario() -> None:
    _helpers.log("calling vrcpilot.launch(no_vr=True)")
    vrcpilot.launch(no_vr=True)

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    # Step from the natural post-launch foreground state through an
    # alternating sequence so each call has an observable effect.
    _helpers.log("calling vrcpilot.unfocus() (1/4: leave initial foreground)")
    assert vrcpilot.unfocus(), "vrcpilot.unfocus() returned False"
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("focus_unfocus", "1_unfocus")

    _helpers.log("calling vrcpilot.focus() (2/4: return to foreground)")
    assert vrcpilot.focus(), "vrcpilot.focus() returned False"
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("focus_unfocus", "2_focus")

    _helpers.log("calling vrcpilot.unfocus() (3/4: repeat for idempotence)")
    assert vrcpilot.unfocus(), "vrcpilot.unfocus() returned False"
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("focus_unfocus", "3_unfocus")

    _helpers.log("calling vrcpilot.focus() (4/4: repeat for idempotence)")
    assert vrcpilot.focus(), "vrcpilot.focus() returned False"
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("focus_unfocus", "4_focus")


def main() -> int:
    return _helpers.run_scenario("focus_unfocus", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
