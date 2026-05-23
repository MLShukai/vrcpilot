"""VRChat launch helpers: argv assembly and Steam ``-applaunch`` spawn."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import vrcpilot.process as _process
from vrcpilot import steam

from . import (
    PID_WAIT_INTERVAL,
    PID_WAIT_TIMEOUT,
    VRCHAT_STEAM_APP_ID,
)


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
    steam_executable = steam.find_steam_executable(steam_path)
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
    # Look up through the parent package so test patches on
    # ``vrcpilot.process.wait_for_pid`` reach this call.
    return _process.wait_for_pid(timeout=wait_timeout, interval=wait_interval)
