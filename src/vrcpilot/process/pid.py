"""VRChat PID discovery, wait helpers, and termination."""

from __future__ import annotations

import time
from typing import Final

import psutil

from .errors import VRChatMultipleInstancesError, VRChatNotRunningError

#: Process name used by VRChat. On Linux/Steam Deck the client runs under
#: Proton and still presents itself as ``VRChat.exe``, so the same constant
#: is correct on every supported OS.
VRCHAT_PROCESS_NAME: Final[str] = "VRChat.exe"

#: Default total seconds :func:`wait_for_pid` / :func:`wait_for_no_pid`
#: poll before giving up. Sized for Steam's cold-start path on a typical
#: workstation (Steam launcher -> game bootstrapper -> VRChat).
PID_WAIT_TIMEOUT: Final[float] = 30.0

#: Default seconds between polls in :func:`wait_for_pid` /
#: :func:`wait_for_no_pid`. One second keeps the helpers responsive
#: without burning CPU on ``psutil.process_iter`` calls.
PID_WAIT_INTERVAL: Final[float] = 1.0


def find_pids() -> list[int]:
    """Return PIDs of every running VRChat process, newest first.

    Sorted by ``create_time()`` descending so the most-recently-started
    instance is index 0 — what a fresh :func:`launch` typically wants.

    Processes whose ``create_time()`` raises ``NoSuchProcess`` /
    ``AccessDenied`` are silently dropped. ``AccessDenied`` is normal on
    Windows for VRChat instances owned by another user session; treating
    it as an error would make cross-session enumeration explode. The
    downstream cost: if the *only* running VRChat is hidden behind
    ``AccessDenied``, :func:`resolve_pid` will report "not running".
    """
    pairs: list[tuple[float, int]] = []
    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] != VRCHAT_PROCESS_NAME:
            continue
        try:
            ct = proc.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        pairs.append((ct, proc.pid))
    pairs.sort(key=lambda kv: kv[0], reverse=True)
    return [pid for _, pid in pairs]


def resolve_pid(pid: int | None) -> int:
    """Resolve an explicit or implicit VRChat target PID to a concrete int.

    When *pid* is provided, return it unchanged (no liveness check — callers
    handle a stale PID at the syscall boundary). When *pid* is ``None``,
    consult :func:`find_pids`:

    * 0 matches → :class:`VRChatNotRunningError`
    * 1 match → return that PID
    * 2+ matches → :class:`VRChatMultipleInstancesError` listing all candidates

    Does **not** read ``VRCPILOT_TARGET_PID`` or any other environment variable
    (the env-var approach is intentionally avoided to prevent silent
    cross-command contamination).
    """
    if pid is not None:
        return pid
    pids = find_pids()
    if not pids:
        raise VRChatNotRunningError("VRChat is not running")
    if len(pids) > 1:
        raise VRChatMultipleInstancesError(pids)
    return pids[0]


def wait_for_pid(
    timeout: float = PID_WAIT_TIMEOUT,
    interval: float = PID_WAIT_INTERVAL,
    *,
    pid: int | None = None,
) -> int | None:
    """Poll for a VRChat PID until one appears or ``timeout`` elapses.

    With ``pid=None`` (default), returns the newest VRChat PID once at
    least one instance is running. The "newest" comes from
    :func:`find_pids` (descending ``create_time``), so the most recently
    started process wins.

    With ``pid=<int>`` specified, polls ``psutil.pid_exists(pid)`` and
    returns that exact PID once it's alive. Useful for waiting on a
    specific instance after a multi-instance launch.

    Returns ``None`` if the deadline expired before the condition was
    met.
    """
    deadline = time.monotonic() + timeout
    while True:
        if pid is None:
            pids = find_pids()
            if pids:
                return pids[0]
        elif psutil.pid_exists(pid):
            return pid
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def wait_for_no_pid(
    timeout: float = PID_WAIT_TIMEOUT,
    interval: float = PID_WAIT_INTERVAL,
    *,
    pid: int | None = None,
) -> bool:
    """Poll until VRChat is no longer running, or ``timeout`` elapses.

    With ``pid=None`` (default), waits until :func:`find_pids` returns
    an empty list — i.e. every VRChat instance has exited.

    With ``pid=<int>`` specified, polls ``psutil.pid_exists(pid)`` and
    returns once that specific PID is gone (other VRChat instances may
    still be running).

    Returns ``True`` when the condition was met before timeout, ``False``
    otherwise.
    """
    deadline = time.monotonic() + timeout
    while True:
        if pid is None:
            if not find_pids():
                return True
        elif not psutil.pid_exists(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def terminate(*pids: int, timeout: float = 5.0) -> list[int]:
    """Forcefully ``kill`` VRChat processes.

    With no positional arguments, kills every running VRChat process
    (legacy behavior). With explicit ``pids``, kills only those PIDs.
    Each explicit PID is validated against
    ``psutil.Process(pid).name() == VRCHAT_PROCESS_NAME`` before
    issuing ``kill()`` so an unrelated process is never terminated by
    mistake.

    Args:
        *pids: Optional explicit PIDs to kill. When empty, every
            running VRChat process is targeted.
        timeout: Seconds to wait for the killed processes to exit
            after ``kill()`` is issued.

    Returns:
        The PIDs that received ``kill()``. Empty when nothing matched
        (no VRChat running and no explicit PIDs given, or every
        explicit PID was already gone).

    Raises:
        ValueError: An explicit PID exists but is not a VRChat process
            (``psutil.Process.name()`` mismatch).
            ``psutil.NoSuchProcess`` for a missing PID is *not* an
            error — it is silently skipped so callers can re-run
            ``terminate`` idempotently.
    """
    targets: list[psutil.Process]
    if pids:
        targets = []
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                name = proc.name()
            except psutil.NoSuchProcess:
                # Already gone -- treat as success for idempotent callers.
                continue
            if name != VRCHAT_PROCESS_NAME:
                raise ValueError(f"PID {pid} is not a VRChat process (name={name!r})")
            targets.append(proc)
    else:
        targets = [
            p
            for p in psutil.process_iter(["name"])
            if p.info["name"] == VRCHAT_PROCESS_NAME
        ]

    if not targets:
        return []
    # Snapshot pids before kill: psutil keeps ``pid`` valid post-kill,
    # but reading it eagerly is the defensive choice.
    killed_pids = [p.pid for p in targets]
    for proc in targets:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            # Process exited between enumeration and kill - treat as success.
            pass
    psutil.wait_procs(targets, timeout=timeout)
    return killed_pids
