"""E2E scenario: launch VRChat with the ``--no-vr`` flag.

Verifies that :func:`vrcpilot.launch` succeeds with ``no_vr=True`` on a
machine that may not have an HMD attached, that a PID becomes visible,
remains stable after a warm-up window, and that termination reports
success.

Run with::

    just e2e-test launch_no_vr
"""

from __future__ import annotations

import sys
from pathlib import Path

import vrcpilot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

_NO_VR_WARMUP_SECONDS: float = 20.0


def _scenario() -> None:
    _helpers.log("launching VRChat with no_vr=True")
    vrcpilot.launch(no_vr=True)

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID did not appear within timeout"
    _helpers.log(f"VRChat PID detected: {pid}")

    _helpers.warmup(_NO_VR_WARMUP_SECONDS)

    pids_after = vrcpilot.find_pids()
    assert pids_after == [
        pid
    ], f"VRChat PID changed after warmup (before={pid}, after={pids_after})"
    _helpers.log(f"VRChat PID stable after warmup: {pids_after[0]}")

    _helpers.log("terminating VRChat")
    assert vrcpilot.terminate(), "vrcpilot.terminate() returned [] (no VRChat killed)"
    _helpers.log("terminate reported success")


def main() -> int:
    return _helpers.run_scenario("launch_no_vr", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
