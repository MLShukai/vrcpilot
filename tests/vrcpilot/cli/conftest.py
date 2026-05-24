"""Shared fixtures for the :mod:`vrcpilot.cli` test suite.

The autouse fixture pins ``sys.stdin.isatty()`` to ``True`` for every
CLI test by default. ``vrcpilot.cli._common.resolve_screenshot`` takes
the piped-stdin branch whenever stdin is not a tty, but pytest runners
under common harnesses (uv, CI containers) leave stdin as a non-tty
pipe -- without this fixture, ``ocr`` / ``detect`` / ``paste`` /
``osc chatbox`` tests that do not explicitly pipe payload would read
garbage from the test runner's stdin.

Tests that explicitly cover the stdin route override this default by
patching ``vrcpilot.cli._common.sys.stdin`` (or the per-subcommand
``sys.stdin`` binding) with a ``StringIO`` whose ``isatty()`` naturally
returns ``False``; the explicit patch shadows the autouse default and
is unwound first when the test ends.

POLICY EXCEPTION: ``sys.stdin`` patching is treated as a pragmatic
exception to the project-wide ban on 3rd-party / stdlib surface mocks
(see ``.claude/skills/vrcpilot-testing/SKILL.md``). The substitutions
do not fake stdlib behaviour -- they replace stdin with a
plain ``io.StringIO`` whose ``isatty()`` and ``read()`` are the
genuine stdlib implementations -- so the only "patching" is the
test-harness-side TTY plumbing the runner cannot otherwise expose.
The cleaner long-term fix is to add a ``stdin`` keyword argument to
``cli._common.resolve_screenshot`` / ``cli.paste.run`` / ``cli.osc.run``
so tests can inject ``io.StringIO`` directly; until that production
refactor lands, the patching pattern stays.
"""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture


@pytest.fixture(autouse=True)
def _stdin_is_tty_by_default(mocker: MockerFixture) -> None:
    """Default ``sys.stdin.isatty()`` to ``True`` for CLI tests."""
    mocker.patch("vrcpilot.cli._common.sys.stdin.isatty", return_value=True)


@pytest.fixture
def not_wayland_native(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable native-Wayland detection so ``ensure_target`` keeps going.

    :func:`vrcpilot.session.is_wayland_native` returns ``True`` when
    ``XDG_SESSION_TYPE == "wayland"`` and ``DISPLAY`` is unset. The
    ``controls.guard.ensure_target`` path raises
    :class:`NotImplementedError` in that case rather than falling
    through to :func:`vrcpilot.process.resolve_pid`; the CLI does not
    catch that, so an unrelated test failure mode leaks out. Clearing
    the env var keeps focus-guard tests deterministic across hosts.
    """
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
