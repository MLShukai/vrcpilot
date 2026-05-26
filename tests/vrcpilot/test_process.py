"""Tests for :mod:`vrcpilot.process`'s pid / wait / terminate APIs.

What is covered here vs. elsewhere:

* **PID discovery** (``find_pids``, ``resolve_pid``):
  the autouse conftest fixture ``_no_real_vrchat`` pins
  ``psutil.process_iter`` to an empty iterator, so every test in this
  module observes "no VRChat running" by default. That gives us the
  negative case for free. The **positive case** ("find_pids returns a
  PID when VRChat IS running") requires a real ``VRChat.exe``
  process and is covered by ``tests/e2e/`` -- the policy forbids
  individual tests from re-patching ``psutil.process_iter``.

* **Wait helpers** (``wait_for_pid``, ``wait_for_no_pid``) use real
  short timeouts to exercise the polling loop end-to-end. With the
  autouse empty ``process_iter``, ``wait_for_pid(pid=None, timeout=0.05)``
  returns ``None`` after one real poll cycle. ``pid=<int>`` mode is
  driven by real ``psutil.pid_exists`` against actual subprocesses we
  spawn (and an obviously-non-existent high PID for the absent case).

* **``terminate``** is exercised against real subprocesses spawned via
  ``subprocess.Popen([sys.executable, "-c", "import time;
  time.sleep(N)"])``. The spawned process's name is ``python``-ish,
  never ``VRChat.exe``, so ``terminate(child.pid)`` triggers the
  "not a VRChat process" guard for free. We never spawn a real
  ``VRChat.exe``, so the success-path kill is e2e-only.

* **Public exceptions** (``VRChatMultipleInstancesError``): only the
  ``pids`` payload (a load-bearing attribute the public API exposes)
  is verified; subclass relationships are not retested (pyright +
  Python language guarantee them).
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator

import psutil
import pytest

from vrcpilot.process import (
    PID_WAIT_INTERVAL,
    PID_WAIT_TIMEOUT,
    VRChatMultipleInstancesError,
    VRChatNotRunningError,
    find_pids,
    resolve_pid,
    terminate,
    wait_for_no_pid,
    wait_for_pid,
)


@pytest.fixture
def short_lived_subprocess() -> Iterator[subprocess.Popen[bytes]]:
    """Spawn a real child process that sleeps long enough for assertions.

    Yields the live ``Popen`` object so tests can read ``child.pid``.
    On teardown the child is killed (idempotent: a test that already
    killed it will see no error). 5 seconds is plenty for any single
    assertion in this module; the polling loops use sub-second
    timeouts so the test itself completes in ms.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield child
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5.0)


def _doomed_pid() -> int:
    """Return a PID that is guaranteed to not exist on this host.

    Spawn a tiny child, capture its PID, then ``wait()`` for it to
    fully exit. The captured PID is now historical -- ``psutil`` will
    raise ``NoSuchProcess`` for it. This is more reliable than picking
    a "very high" number which can collide on long-running hosts.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = child.pid
    child.wait(timeout=5.0)
    # Poll psutil until the PID is actually gone -- on some kernels
    # the process briefly lingers as a zombie before being reaped.
    deadline = time.monotonic() + 5.0
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return pid


class TestFindPids:
    """``find_pids`` enumerates all VRChat instances, newest first.

    The autouse empty-iterator gives us the empty-list case. The
    populated cases (single, multiple, ordering by ``create_time``,
    skipping AccessDenied / NoSuchProcess) require real ``VRChat.exe``
    processes and are e2e-only.
    """

    def test_returns_empty_list_when_no_vrchat_running(self):
        assert find_pids() == []


class TestResolvePid:
    """``resolve_pid`` returns an explicit PID verbatim, or consults
    ``find_pids`` when ``None``."""

    def test_explicit_pid_returned_verbatim_without_liveness_check(self):
        # Documented behaviour: no liveness check on an explicit PID.
        # Even a clearly-fake PID must be returned as-is so callers
        # can address a pre-known instance without an extra syscall.
        assert resolve_pid(999) == 999

    def test_raises_not_running_when_no_pid_and_nothing_running(self):
        # autouse: find_pids() is empty -> VRChatNotRunningError.
        with pytest.raises(VRChatNotRunningError, match="not running"):
            resolve_pid(None)


class TestVRChatMultipleInstancesError:
    """The exception's ``pids`` attribute is a load-bearing public field.

    Subclass relationship (``isinstance(err, VRChatNotRunningError)``)
    is not re-tested here -- Python's class system guarantees it.
    """

    def test_pids_attribute_is_independent_copy_of_caller_list(self):
        # The constructor stores ``list(pids)`` so the caller's later
        # mutations do not bleed into the exception's record. Critical
        # because the err.pids payload is what API consumers act on
        # when deciding which instance to target.
        source = [10, 20]

        err = VRChatMultipleInstancesError(source)
        source.append(30)

        assert err.pids == [10, 20]

    def test_message_includes_candidate_pids(self):
        # The message must surface the candidate PIDs so a CLI / e2e
        # log can identify which instances were ambiguous.
        err = VRChatMultipleInstancesError([111, 222])

        assert "111" in str(err)
        assert "222" in str(err)


class TestWaitForPid:
    """``wait_for_pid`` polls until a VRChat PID appears or timeout.

    Two modes:

    * ``pid=None`` -> waits for ANY VRChat (positive case is e2e).
    * ``pid=<int>`` -> waits for that exact PID via real
      ``psutil.pid_exists``; both branches (alive / dead) are testable
      with a real spawned subprocess.
    """

    def test_returns_none_on_timeout_when_no_vrchat_running(self):
        # autouse: process_iter empty -> find_pids() never returns a
        # PID. With a tiny timeout the real wall-clock loop exits
        # quickly without any patching of time.sleep.
        start = time.monotonic()

        result = wait_for_pid(timeout=0.05, interval=0.01)

        elapsed = time.monotonic() - start
        assert result is None
        # The loop must actually respect the timeout, not block forever.
        assert elapsed < 2.0

    def test_returns_specific_pid_immediately_when_alive(
        self, short_lived_subprocess: subprocess.Popen[bytes]
    ):
        # The pid= mode bypasses find_pids() entirely; it polls
        # psutil.pid_exists() against the real PID we just spawned.
        result = wait_for_pid(
            timeout=2.0, interval=0.01, pid=short_lived_subprocess.pid
        )

        assert result == short_lived_subprocess.pid

    def test_returns_none_when_specific_pid_is_dead(self):
        # A PID for a process that has already exited will never satisfy
        # psutil.pid_exists; the helper must respect the timeout and
        # return None, not loop forever.
        result = wait_for_pid(timeout=0.05, interval=0.01, pid=_doomed_pid())

        assert result is None

    def test_default_timeout_matches_module_constant(self):
        # The default timeout / interval must remain the
        # documented module-level constants so e2e tooling that imports
        # PID_WAIT_TIMEOUT receives the same value the wait helpers
        # use. Catches a regression where the default drifts away from
        # the documented constant.
        assert wait_for_pid.__defaults__ == (PID_WAIT_TIMEOUT, PID_WAIT_INTERVAL)


class TestWaitForNoPid:
    """``wait_for_no_pid`` polls until VRChat is gone or timeout."""

    def test_returns_true_immediately_when_no_vrchat_running(self):
        # autouse: find_pids() is empty from the start -> first poll
        # satisfies the predicate. Must NOT sleep before returning.
        start = time.monotonic()

        result = wait_for_no_pid(timeout=5.0, interval=1.0)

        elapsed = time.monotonic() - start
        assert result is True
        # Generous bound: the helper should return before the 1.0s
        # interval would tick once.
        assert elapsed < 0.5

    def test_returns_false_when_specific_pid_still_alive_after_timeout(
        self, short_lived_subprocess: subprocess.Popen[bytes]
    ):
        # The pid= mode polls real psutil.pid_exists; while the child
        # is alive the predicate is never satisfied within timeout.
        result = wait_for_no_pid(
            timeout=0.1, interval=0.01, pid=short_lived_subprocess.pid
        )

        assert result is False

    def test_returns_true_when_specific_pid_already_dead(self):
        # A PID for an already-reaped process: psutil.pid_exists is
        # False immediately, the helper returns True without timing out.
        result = wait_for_no_pid(timeout=2.0, interval=0.01, pid=_doomed_pid())

        assert result is True

    def test_default_timeout_matches_module_constant(self):
        assert wait_for_no_pid.__defaults__ == (
            PID_WAIT_TIMEOUT,
            PID_WAIT_INTERVAL,
        )


class TestTerminateNoArgs:
    """``terminate()`` with no args targets every running VRChat."""

    def test_returns_empty_list_when_no_vrchat_running(self):
        # autouse: process_iter empty -> nothing to kill -> [].
        assert terminate() == []


class TestTerminateExplicitPid:
    """``terminate(pid)`` validates name before killing.

    The success path (real VRChat kill) is e2e-only. The two failure
    modes are testable here:

    * non-existent PID -> silently skipped (returns []).
    * existing PID with wrong name -> ValueError, never killed.
    """

    def test_silently_skips_non_existent_pid(self):
        # An already-reaped PID raises NoSuchProcess from
        # psutil.Process(pid); terminate() must treat that as
        # "already gone" so callers can re-invoke it idempotently.
        assert terminate(_doomed_pid()) == []

    def test_refuses_to_kill_non_vrchat_pid(
        self, short_lived_subprocess: subprocess.Popen[bytes]
    ):
        # The subprocess we spawned is a Python interpreter, not
        # VRChat.exe. The name validation must fire and ValueError
        # must be raised BEFORE any kill is issued.
        pid = short_lived_subprocess.pid

        with pytest.raises(ValueError, match="not a VRChat process"):
            terminate(pid)

        # Critical: the impostor is still alive. The fixture's
        # teardown will kill it cleanly.
        assert short_lived_subprocess.poll() is None
        # Sanity check: the name we matched against was indeed not
        # "VRChat.exe".
        assert psutil.Process(pid).name() != "VRChat.exe"

    def test_mixed_existing_and_missing_pids_skips_missing(
        self, short_lived_subprocess: subprocess.Popen[bytes]
    ):
        # When some explicit PIDs are gone and some are alive (but not
        # VRChat), validation must surface the wrong-name ValueError
        # from the alive one rather than swallowing it. Documents the
        # ordering: a missing PID earlier in the args list does not
        # short-circuit a downstream impostor's validation.
        with pytest.raises(ValueError, match="not a VRChat process"):
            terminate(_doomed_pid(), short_lived_subprocess.pid)

        # Impostor still alive.
        assert short_lived_subprocess.poll() is None


# NOTE: The success path of terminate() -- actually killing a running
# VRChat.exe and observing psutil.wait_procs() complete -- requires a
# real VRChat instance and lives in tests/e2e/. find_pids() with a
# populated result (single / multi / create_time ordering / AccessDenied
# skip) is similarly e2e-only because the test policy forbids
# individual tests from re-patching ``vrcpilot.process.pid.psutil.process_iter``.
