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


class VRChatDisplayNotAvailableError(RuntimeError):
    """Raised when ``launch()`` (direct-spawn) is invoked on Linux without a
    graphical display attached.

    The umu-run + Wine subprocess needs a display server to draw into.
    With neither ``$DISPLAY`` (X11 / XWayland) nor ``$WAYLAND_DISPLAY``
    (Wayland-native) set, umu-run does not fail fast — it hangs waiting
    for a server. vrcpilot detects this pre-spawn so callers (notably
    the e2e harness running over plain SSH) see an immediate, actionable
    error instead of a stuck process.

    Only the direct-spawn route is gated; ``via_steam=True`` delegates
    display setup to the already-running Steam desktop client and is
    instead pre-flighted by a Steam-process-running check.
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
        "find_pid() is deprecated and will be removed in 0.4.0; "
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
    ``psutil.AccessDenied`` are silently skipped. ``AccessDenied`` is the
    common failure mode for cross-session VRChat instances on Windows (e.g.
    one started by another user), so a skipped process is not a hard error
    here. The downstream consequence is that if the *only* running VRChat is
    in that state, :func:`resolve_pid` (called with ``pid=None``) will report
    it as not running and raise :class:`VRChatNotRunningError`. Returns an
    empty list when no VRChat instance is running.
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
    "VRChatDisplayNotAvailableError",
    "VRChatLauncherNotFoundError",
    "VRChatMultipleInstancesError",
    "VRChatNotRunningError",
    "wait_for_no_pid",
    "wait_for_pid",
]
