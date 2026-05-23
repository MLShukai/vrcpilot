"""Project-wide pytest fixtures.

The autouse fixture here is a *safety valve*: it isolates the test
suite from a real VRChat process that may happen to be running on a
developer's local machine. Without it, a `find_pid()` call in the
production code path would observe the live PID and tests that assume
"no VRChat" would behave inconsistently between CI and local runs.

Tests that need ``find_pid`` to return a specific PID can override the
autouse default by patching ``vrcpilot.process.pid.psutil.process_iter``
inside the test (e.g. via ``mocker.patch``); the explicit patch
shadows the autouse monkeypatch and is unwound first when the test
ends.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _no_real_vrchat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default ``psutil.process_iter`` to an empty iterator for every test.

    Ensures :func:`vrcpilot.find_pid` returns ``None`` and
    :func:`vrcpilot.terminate` is a no-op unless a test deliberately
    populates the iterator. Local development environments where
    VRChat is running should not pollute test outcomes.
    """

    def _empty(*_args: object, **_kwargs: object) -> Iterator[object]:
        return iter([])

    monkeypatch.setattr("vrcpilot.process.pid.psutil.process_iter", _empty)
