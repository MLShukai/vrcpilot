"""Project-wide pytest fixtures.

This module contains the **single, deliberate exception** to the
project rule that test code MUST NOT patch 3rd-party library surfaces
(`.claude/skills/vrcpilot-testing/SKILL.md`).

The autouse :func:`_no_real_vrchat` fixture patches
``vrcpilot.process.pid.psutil.process_iter`` *for environment
isolation*, not for behavioural mocking. A developer machine that
happens to be running VRChat would otherwise leak that PID into every
test through :func:`vrcpilot.find_pids`, producing different results
between CI (no VRChat) and local runs (VRChat present). This is
infrastructure isolation, equivalent in spirit to ``tmp_path`` or
``Xvfb`` -- not a per-test mock.

This exception is **scoped to this conftest only**. Per-test files
under ``tests/vrcpilot/`` MUST NOT patch ``psutil.process_iter``,
``psutil.Process``, or any other 3rd-party surface for behavioural
verification. Tests that need to exercise :func:`vrcpilot.find_pids`
against a specific process state should spawn a real subprocess and
verify the observable behaviour, or escalate to the orchestrator
when no real-resource path exists.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _no_real_vrchat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default ``psutil.process_iter`` to an empty iterator for every test.

    Environment isolation -- see the module docstring for why this is
    the one place ``psutil`` patching is permitted. The patch is autouse
    so a local VRChat process cannot pollute test outcomes; it does
    NOT exist to let individual tests substitute a different iterator.
    """

    def _empty(*_args: object, **_kwargs: object) -> Iterator[object]:
        return iter([])

    monkeypatch.setattr("vrcpilot.process.pid.psutil.process_iter", _empty)
