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


def find_pid() -> int | None:
    """Return the PID of a running VRChat process, or ``None`` if absent.

    Returns the first match from :func:`psutil.process_iter` - when
    multiple instances run, enumeration order is OS-defined and the
    choice is not configurable. Use :func:`find_pids` to retrieve every
    matching PID.
    """
    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] == VRCHAT_PROCESS_NAME:
            return proc.pid
    return None


def find_pids() -> list[int]:
    """Return PIDs of every running VRChat process.

    The order of the returned list reflects the OS-defined enumeration
    order of :func:`psutil.process_iter` and should not be treated as
    stable across runs. Returns an empty list when no VRChat instance
    is running.
    """
    return [
        proc.pid
        for proc in psutil.process_iter(["name"])
        if proc.info["name"] == VRCHAT_PROCESS_NAME
    ]


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
    "terminate",
    "VRCHAT_PROCESS_NAME",
    "VRCHAT_STEAM_APP_ID",
    "VRChatNotRunningError",
    "wait_for_no_pid",
    "wait_for_pid",
]
