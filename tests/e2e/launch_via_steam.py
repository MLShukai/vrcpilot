"""E2E scenario: launch VRChat via the legacy Steam route and terminate it.

Mirrors :mod:`tests.e2e.launch_terminate` but exercises the
``via_steam=True`` code path explicitly, so the legacy
``steam.exe -applaunch`` route stays verified against a real install
even after the default switched to direct-spawn.

Run with::

    uv run python tests/e2e/launch_via_steam.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import vrcpilot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402


def _scenario() -> None:
    _helpers.log("calling vrcpilot.launch(via_steam=True)")
    pid = vrcpilot.launch(via_steam=True)
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    pids_after = vrcpilot.find_pids()
    assert pids_after == [pid], (
        f"VRChat PID changed or disappeared after warmup "
        f"(before={pid}, after={pids_after})"
    )
    _helpers.log(f"VRChat still alive after warmup (pid={pid})")

    _helpers.log("terminating VRChat")
    assert vrcpilot.terminate(), "vrcpilot.terminate() returned [] (no VRChat killed)"
    _helpers.log("VRChat terminated")


def main() -> int:
    return _helpers.run_scenario("launch_via_steam", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
