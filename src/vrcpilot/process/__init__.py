"""VRChat process lifecycle: launch, find, terminate."""

from __future__ import annotations

# ``subprocess`` is re-exported as ``subprocess as subprocess`` (PEP 484
# explicit re-export idiom) so existing tests that monkeypatch
# ``vrcpilot.process.subprocess.Popen`` keep resolving. The real call
# site is :mod:`vrcpilot.process.launch`; because ``subprocess`` is a
# singleton in ``sys.modules``, patching ``Popen`` on this attribute
# reaches the call site identically.
import subprocess as subprocess
import time
import warnings
from typing import Final

import psutil

#: Steam application id for VRChat.
VRCHAT_STEAM_APP_ID: Final[int] = 438100

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


class VRChatNotRunningError(RuntimeError):
    """No VRChat process is running when an input was requested."""


class VRChatMultipleInstancesError(VRChatNotRunningError):
    """Raised when no pid is specified but multiple VRChat instances are
    running.

    Subclass of :class:`VRChatNotRunningError` so existing ``except`` blocks
    still catch it. The candidate PIDs are exposed via :attr:`pids` (newest first,
    matching :func:`find_pids`'s ordering).
    """

    pids: list[int]

    def __init__(self, pids: list[int]) -> None:
        super().__init__(
            f"multiple VRChat instances detected (PIDs: {pids}); "
            "pass pid= to disambiguate"
        )
        self.pids = list(pids)


class VRChatLauncherNotFoundError(RuntimeError):
    """Raised when VRChat's ``launch.exe`` (EAC wrapper) cannot be located.

    The body of :func:`find_vrchat_launcher` (added in C2) raises this when
    every discovery strategy fails.
    """


class VRChatAlreadyRunningError(RuntimeError):
    """Raised when ``launch(via_steam=True)`` is called while VRChat is already
    running.

    ``steam.exe -applaunch`` simply focuses the existing instance instead of
    spawning a new one, so the call would never observe a new PID. C8 will
    use this; defining it here keeps the public exception surface consistent.
    """


class UmuLauncherNotFoundError(RuntimeError):
    """Raised when Linux direct-spawn cannot find ``umu-run`` on PATH.

    C2 / C8 use this; defining it here keeps the public exception
    surface consistent.
    """


def find_pid() -> int | None:
    """Return the newest VRChat PID, or ``None`` if absent. **Deprecated.**

    .. deprecated:: 0.3.0
        Will be removed in 0.4.0. Use :func:`find_pids` to enumerate all
        instances, or pass ``pid=`` to specific APIs to target one explicitly.

    Equivalent to ``find_pids()[0] if find_pids() else None`` — i.e. the
    newest-started VRChat by ``create_time`` ordering.
    """
    warnings.warn(
        "vrcpilot.process.find_pid is deprecated and will be removed in 0.4.0; "
        "use find_pids() or pass pid= to specific APIs",
        DeprecationWarning,
        stacklevel=2,
    )
    pids = find_pids()
    return pids[0] if pids else None


def find_pids() -> list[int]:
    """Return PIDs of every running VRChat process, newest first.

    Sorted by ``psutil.Process.create_time()`` in **descending** order so the
    most-recently-started VRChat appears first. Useful when multiple instances
    run and the caller wants the freshly launched one.

    Processes whose ``create_time()`` raises ``psutil.NoSuchProcess`` or
    ``psutil.AccessDenied`` are silently skipped. Returns an empty list when
    no VRChat instance is running.
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
) -> int | None:
    """Poll for a VRChat PID until one appears or ``timeout`` elapses.

    Uses :func:`find_pid` so the first match wins (enumeration order
    is OS-defined). Returns ``None`` if the deadline expired before
    any VRChat process appeared.
    """
    deadline = time.monotonic() + timeout
    while True:
        pid = find_pid()
        if pid is not None:
            return pid
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def wait_for_no_pid(
    timeout: float = PID_WAIT_TIMEOUT,
    interval: float = PID_WAIT_INTERVAL,
) -> bool:
    """Poll until no VRChat process is running, or ``timeout`` elapses.

    Mirror of :func:`wait_for_pid` for the teardown path. Useful after
    :func:`terminate` to confirm the kill actually settled. Returns
    ``True`` once VRChat is gone; ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout
    while True:
        if find_pid() is None:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def terminate(*, timeout: float = 5.0) -> list[int]:
    """Forcefully ``kill`` every running VRChat process.

    Returns the PIDs that were issued ``kill()`` (empty when none were
    running). PIDs are returned even if a process is still listed after
    ``timeout`` — the kill was issued, only the wait did not observe
    completion.
    """
    procs = [
        p
        for p in psutil.process_iter(["name"])
        if p.info["name"] == VRCHAT_PROCESS_NAME
    ]
    if not procs:
        return []
    # Snapshot pids before kill: psutil keeps ``pid`` valid post-kill,
    # but reading it eagerly is the defensive choice.
    killed_pids = [p.pid for p in procs]
    for proc in procs:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            # Process exited between enumeration and kill - treat as success.
            pass
    psutil.wait_procs(procs, timeout=timeout)
    return killed_pids


# Re-export launch helpers so ``from vrcpilot.process import launch`` etc.
# keeps working. Imported at the bottom to avoid a circular import:
# :mod:`vrcpilot.process.launch` needs the constants and ``wait_for_pid``
# defined above.
from .launch import (  # noqa: E402
    OscConfig,
    build_launch_command,
    build_vrchat_launch_args,
    launch,
)

__all__ = [
    "build_launch_command",
    "build_vrchat_launch_args",
    "find_pid",
    "find_pids",
    "launch",
    "OscConfig",
    "PID_WAIT_INTERVAL",
    "PID_WAIT_TIMEOUT",
    "resolve_pid",
    "terminate",
    "UmuLauncherNotFoundError",
    "VRCHAT_PROCESS_NAME",
    "VRCHAT_STEAM_APP_ID",
    "VRChatAlreadyRunningError",
    "VRChatLauncherNotFoundError",
    "VRChatMultipleInstancesError",
    "VRChatNotRunningError",
    "wait_for_no_pid",
    "wait_for_pid",
]
