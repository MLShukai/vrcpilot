"""E2E scenario: launch VRChat via the API and terminate it cleanly.

Drives the public ``vrcpilot`` API through a single happy-path round trip
(``launch`` -> wait for PID -> warmup -> ``find_pid`` again -> ``terminate``)
to confirm the default launch flow works against a real VRChat install.

Run with::

    uv run python tests/e2e/launch_terminate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import vrcpilot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402


def _scenario() -> None:
    _helpers.log("calling vrcpilot.launch()")
    pid = vrcpilot.launch()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    pid_after = vrcpilot.find_pid()
    assert pid_after == pid, (
        f"VRChat PID changed or disappeared after warmup "
        f"(before={pid}, after={pid_after})"
    )
    _helpers.log(f"VRChat still alive after warmup (pid={pid_after})")

    _helpers.log("terminating VRChat")
    assert vrcpilot.terminate(), "vrcpilot.terminate() returned [] (no VRChat killed)"
    _helpers.log("VRChat terminated")


def main() -> int:
    return _helpers.run_scenario("launch_terminate", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
