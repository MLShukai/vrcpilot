"""Project-wide pytest fixtures.

This module contains the **single, deliberate exception** to the
project rule that test code MUST NOT patch library surfaces
(`.claude/skills/vrcpilot-testing/SKILL.md`).

The autouse :func:`_no_real_vrchat` fixture forces VRChat discovery to
"nothing running" *for environment isolation*, not for behavioural
mocking. A developer machine that happens to be running VRChat would
otherwise leak that PID into every test through
:func:`vrcpilot.find_pids`, producing different results between CI (no
VRChat) and local runs (VRChat present). This is infrastructure
isolation, equivalent in spirit to ``tmp_path`` or ``Xvfb`` -- not a
per-test mock.

Two seams are pinned because the scan moved to the native extension:

* ``vrcpilot._native.process.find_pids`` -- backs :func:`find_pids`
  (and therefore ``resolve_pid``); this replaced the old
  ``psutil.process_iter`` scan.
* ``vrcpilot.process.pid.psutil.process_iter`` -- still backs
  ``terminate()``'s no-argument "kill every VRChat" path.

This exception is **scoped to this conftest only**. Per-test files
under ``tests/vrcpilot/`` MUST NOT patch these (or any other 3rd-party
surface) for behavioural verification. Tests that need to exercise
:func:`vrcpilot.find_pids` against a specific process state should spawn
a real subprocess and verify the observable behaviour (see the
``integration_real`` tests in ``test_process.py``), or escalate to the
orchestrator when no real-resource path exists.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _no_real_vrchat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force VRChat discovery to "nothing running" for every test.

    Environment isolation -- see the module docstring for why this is
    the one place this patching is permitted. The patch is autouse so a
    local VRChat process cannot pollute test outcomes; it does NOT exist
    to let individual tests substitute a different result.
    """
    from vrcpilot import _native

    def _empty(*_args: object, **_kwargs: object) -> Iterator[object]:
        return iter([])

    # find_pids() -> resolve_pid() now scan via the native extension.
    monkeypatch.setattr(_native.process, "find_pids", list)
    # terminate() with no args still enumerates via psutil.process_iter.
    monkeypatch.setattr("vrcpilot.process.pid.psutil.process_iter", _empty)
