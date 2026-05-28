"""E2E scenario: run two VRChat instances side-by-side with ``--profile``.

VRChat ships ``--profile=N`` so multiple accounts can coexist with
separated SaveData folders (and, on Linux, separate auto-generated
wineprefixes). ``vrcpilot`` exposes that contract through three pieces:

* :func:`vrcpilot.find_pids` returns *every* live VRChat PID,
  newest first.
* :func:`vrcpilot.process.resolve_pid` raises
  :class:`vrcpilot.VRChatMultipleInstancesError` when no explicit PID
  is given and more than one instance is running.
* :func:`vrcpilot.launch` with ``via_steam=True`` fails fast with
  :class:`~vrcpilot.process.VRChatAlreadyRunningError` if any instance
  exists, because ``steam.exe -applaunch`` would refocus rather than
  spawn.
* :func:`vrcpilot.terminate` kills one PID, several, or (no args) all.

The earlier ``launch_terminate`` scenarios only ever observe a single
process, so this script is the only place where the multi-instance
side of those contracts is exercised against a real VRChat install.

Run with::

    uv run python tests/e2e/multi_instance.py

The script launches with ``no_vr=True`` because running two VRChats in
VR mode would fight over the HMD; ``--no-vr`` lets both run as ordinary
desktop windows.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import vrcpilot
from vrcpilot.process import VRChatAlreadyRunningError, resolve_pid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

# Linux generates a fresh wineprefix per profile under
# ``$XDG_DATA_HOME/vrcpilot/profiles/<N>/wineprefix`` on first use. That
# initial Wine/Proton boot can take well over the default 30 s PID wait,
# so allow more headroom; subsequent runs hit the cached prefix and
# return quickly. ``profile=0`` is deliberately avoided here because on
# Linux it points at the Steam-managed ``compatdata/438100/pfx``, which
# is the *shared* prefix rather than an isolated one — this scenario is
# about isolation, so we use slots 1 and 2.
_LAUNCH_WAIT_TIMEOUT: float = 180.0

# On Windows, VRChat boots EasyAntiCheat as part of every launch. Starting
# the second instance while the first instance's EAC bootstrap is still in
# flight makes the second launch fail to spawn its process (EAC serializes /
# refuses the concurrent start), so ``launch(profile=2)`` never observes a
# PID before the timeout. Let the first instance settle past its EAC
# bootstrap before launching the second.
_INTER_LAUNCH_DELAY: float = 5.0


def _scenario() -> None:
    _helpers.log("launching profile=1 (no_vr=True)")
    pid_a = vrcpilot.launch(profile=1, no_vr=True, wait_timeout=_LAUNCH_WAIT_TIMEOUT)
    assert pid_a is not None, "profile=1 launch did not observe a PID before timeout"
    _helpers.log(f"profile=1 PID = {pid_a}")

    _helpers.log(
        f"waiting {_INTER_LAUNCH_DELAY:.0f}s for profile=1 EasyAntiCheat "
        "bootstrap to settle before launching profile=2"
    )
    time.sleep(_INTER_LAUNCH_DELAY)

    _helpers.log("launching profile=2 (no_vr=True)")
    pid_b = vrcpilot.launch(profile=2, no_vr=True, wait_timeout=_LAUNCH_WAIT_TIMEOUT)
    assert pid_b is not None, "profile=2 launch did not observe a PID before timeout"
    assert pid_b != pid_a, f"profile=2 returned the same PID as profile=1: {pid_b}"
    _helpers.log(f"profile=2 PID = {pid_b}")

    # Single warmup after both are alive -- launch() already waited for
    # each PID to exist, so this only buys time for both processes to
    # settle past the very early boot phase before we exercise the API.
    _helpers.warmup()

    pids = vrcpilot.find_pids()
    assert pids == [pid_b, pid_a], (
        f"find_pids() should return [pid_b, pid_a] in newest-first order, "
        f"got {pids} (pid_a={pid_a}, pid_b={pid_b})"
    )
    _helpers.log(f"find_pids() ordering OK: {pids}")

    try:
        resolved = resolve_pid(None)
    except vrcpilot.VRChatMultipleInstancesError as exc:
        exc_pids = sorted(exc.pids)
        expected = sorted([pid_a, pid_b])
        assert exc_pids == expected, (
            f"VRChatMultipleInstancesError.pids should list both PIDs, "
            f"got {exc_pids} (expected {expected})"
        )
        _helpers.log(f"resolve_pid(None) raised with pids={exc_pids}")
    else:
        raise AssertionError(
            f"resolve_pid(None) should have raised VRChatMultipleInstancesError, "
            f"returned {resolved}"
        )

    try:
        vrcpilot.launch(via_steam=True)
    except VRChatAlreadyRunningError as exc:
        _helpers.log(f"launch(via_steam=True) refused as expected: {exc}")
    else:
        raise AssertionError(
            "launch(via_steam=True) should have raised VRChatAlreadyRunningError "
            "when two VRChat instances are already running"
        )

    pids_after_steam = vrcpilot.find_pids()
    assert sorted(pids_after_steam) == sorted([pid_a, pid_b]), (
        f"find_pids() changed after the refused via_steam launch: "
        f"before={sorted([pid_a, pid_b])}, after={sorted(pids_after_steam)}"
    )

    _helpers.log(f"terminating pid_a={pid_a} only")
    killed = vrcpilot.terminate(pid_a)
    assert killed == [
        pid_a
    ], f"terminate(pid_a) should kill only pid_a, returned {killed}"
    survivors = vrcpilot.find_pids()
    assert survivors == [pid_b], (
        f"after terminate(pid_a), find_pids() should be [pid_b={pid_b}], "
        f"got {survivors}"
    )
    _helpers.log(f"selective terminate OK; pid_b={pid_b} still alive")

    _helpers.log("terminating remaining instance with bare terminate()")
    killed_all = vrcpilot.terminate()
    assert killed_all == [pid_b], (
        f"terminate() should kill the remaining instance pid_b={pid_b}, "
        f"returned {killed_all}"
    )
    final = vrcpilot.find_pids()
    assert final == [], f"find_pids() should be empty after terminate(), got {final}"
    _helpers.log("all VRChat instances terminated")


def main() -> int:
    return _helpers.run_scenario("multi_instance", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
