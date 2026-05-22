"""VRChat process lifecycle: launch, find, terminate."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import psutil

from vrcpilot.steam import find_steam_executable

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


@dataclass(frozen=True)
class OscConfig:
    """Structured form of VRChat's ``--osc=<in>:<ip>:<out>`` launch flag.

    Defaults mirror VRChat's factory OSC settings, so ``OscConfig()``
    forwards the flag explicitly without changing client semantics —
    useful when a deterministic argv is wanted (logging, tests).
    """

    in_port: int = 9000
    out_ip: str = "127.0.0.1"
    out_port: int = 9001

    def to_launch_arg(self) -> str:
        """Render as a single ``--osc=...`` argv token."""
        return f"--osc={self.in_port}:{self.out_ip}:{self.out_port}"


def build_vrchat_launch_args(
    *,
    no_vr: bool = False,
    screen_width: int | None = None,
    screen_height: int | None = None,
    osc: OscConfig | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Assemble the VRChat-side argv that follows ``-applaunch <app_id>``.

    Output order is fixed (``no_vr`` -> screen size -> ``osc`` ->
    ``extra_args``) so the argv is byte-stable across runs. ``extra_args``
    is the escape hatch for flags this helper does not model.
    """
    args: list[str] = []
    if no_vr:
        args.append("--no-vr")
    if screen_width is not None:
        args.extend(["-screen-width", str(screen_width)])
    if screen_height is not None:
        args.extend(["-screen-height", str(screen_height)])
    if osc is not None:
        args.append(osc.to_launch_arg())
    if extra_args:
        args.extend(extra_args)
    return args


def build_launch_command(
    steam_executable: Path,
    app_id: int = VRCHAT_STEAM_APP_ID,
    *,
    vrchat_args: list[str] | None = None,
) -> list[str]:
    """Build the Steam ``-applaunch`` argv for spawning the game.

    Exposed separately from :func:`launch` so callers can inspect, log,
    or wrap the command without spawning. ``steam_executable`` is not
    validated by this helper.
    """
    cmd = [str(steam_executable), "-applaunch", str(app_id)]
    if vrchat_args:
        cmd.extend(vrchat_args)
    return cmd


def launch(
    *,
    app_id: int = VRCHAT_STEAM_APP_ID,
    steam_path: Path | None = None,
    no_vr: bool = False,
    screen_width: int | None = None,
    screen_height: int | None = None,
    osc: OscConfig | None = None,
    extra_args: list[str] | None = None,
    wait_timeout: float = PID_WAIT_TIMEOUT,
    wait_interval: float = PID_WAIT_INTERVAL,
) -> int | None:
    """Launch VRChat through Steam and (optionally) wait for its PID.

    Detached from the parent's process group / session so the calling
    Python script can exit without taking VRChat down with it. After
    spawning Steam, polls :func:`find_pid` until VRChat appears or
    ``wait_timeout`` elapses; pass ``wait_timeout <= 0`` to skip the
    wait. Returns the observed PID, or ``None`` when the wait was
    skipped or expired — timeout does not raise so callers can branch
    on ``None`` if they need a stricter signal.

    Raises:
        SteamNotFoundError: Steam executable cannot be located.
    """
    steam_executable = find_steam_executable(steam_path)
    vrchat_args = build_vrchat_launch_args(
        no_vr=no_vr,
        screen_width=screen_width,
        screen_height=screen_height,
        osc=osc,
        extra_args=extra_args,
    )
    argv = build_launch_command(steam_executable, app_id, vrchat_args=vrchat_args)

    if sys.platform == "win32":
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    if wait_timeout <= 0:
        return None
    return wait_for_pid(timeout=wait_timeout, interval=wait_interval)


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
