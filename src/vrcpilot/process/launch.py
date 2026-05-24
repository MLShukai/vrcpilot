"""VRChat launch flow: direct-spawn (default) and via-Steam fallback.

The default route spawns the EAC wrapper ``launch.exe`` directly because
calling ``VRChat.exe`` itself boots the client into offline mode (EAC is
not initialised). ``via_steam=True`` falls back to
``steam.exe -applaunch <app_id>`` and refuses to run if VRChat is already
up — Steam would only refocus the existing window, never spawn a fresh
instance, so the call would silently lie about "launching".
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .errors import VRChatAlreadyRunningError
from .pid import PID_WAIT_INTERVAL, PID_WAIT_TIMEOUT, find_pids

#: Steam application id for VRChat.
VRCHAT_STEAM_APP_ID: Final[int] = 438100


@dataclass(frozen=True)
class OscConfig:
    """Structured form of VRChat's ``--osc=<in>:<ip>:<out>`` launch flag."""

    in_port: int = 9000
    out_ip: str = "127.0.0.1"
    out_port: int = 9001

    def to_launch_arg(self) -> str:
        """Render as the single ``--osc=<in>:<ip>:<out>`` token VRChat
        parses."""
        return f"--osc={self.in_port}:{self.out_ip}:{self.out_port}"


def build_vrchat_launch_args(
    *,
    no_vr: bool = False,
    screen_width: int | None = None,
    screen_height: int | None = None,
    osc: OscConfig | None = None,
    profile: int | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Assemble the VRChat-side argv that follows ``-applaunch <app_id>``.

    The token order (``no_vr`` -> screen size -> ``osc`` -> ``--profile`` ->
    ``extra_args``) is part of the contract: the e2e harness and Steam
    launch-option captures compare argv byte-for-byte across runs.

    Args:
        profile: Rendered as the single token ``--profile=N`` (the only
            spelling VRChat accepts; ``--profile N`` silently breaks).
        extra_args: Escape hatch for VRChat flags this helper does not
            model. Appended verbatim at the end of the argv.
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
    if profile is not None:
        args.append(f"--profile={profile}")
    if extra_args:
        args.extend(extra_args)
    return args


def build_launch_command(
    steam_executable: Path,
    app_id: int = VRCHAT_STEAM_APP_ID,
    *,
    vrchat_args: list[str] | None = None,
) -> list[str]:
    """Build the Steam ``-applaunch`` argv without spawning.

    Exposed separately from :func:`launch` so callers can inspect, log,
    or wrap the command before deciding to run it. ``steam_executable``
    is taken on trust — existence is the caller's concern.
    """
    cmd = [str(steam_executable), "-applaunch", str(app_id)]
    if vrchat_args:
        cmd.extend(vrchat_args)
    return cmd


def validate_launch_args(
    *,
    via_steam: bool,
    wineprefix: Path | None,
    proton_path: Path | None,
    profile: int | None,
) -> None:
    """Fail-fast cross-check of :func:`launch` argument combinations.

    ``--profile=N`` is accepted on both platforms (VRChat parses it the
    same way regardless of host OS). ``wineprefix`` / ``proton_path``
    are Linux + direct-spawn only — on Windows they signal a config
    copy-paste mistake and are rejected outright.

    Combining any of ``wineprefix`` / ``proton_path`` / ``profile`` with
    ``via_steam=True`` is rejected because the Steam route carries
    those settings through Steam's own launch-options surface; injecting
    them into argv here would silently double-specify or get lost.

    Raises:
        ValueError: One of the rules above was violated. The message
            names the offending combination so the caller can drop the
            wrong flag without guessing.
    """
    if profile is not None and profile < 0:
        raise ValueError(f"profile must be non-negative (got {profile})")

    direct_spawn_only = (
        wineprefix is not None or proton_path is not None or profile is not None
    )
    if direct_spawn_only and via_steam:
        raise ValueError(
            "wineprefix/proton_path/profile are only meaningful with "
            "direct-spawn (not --via-steam)"
        )
    if sys.platform == "win32" and (wineprefix is not None or proton_path is not None):
        raise ValueError("wineprefix/proton_path are Linux-only")


def _wait_for_new_pid(
    pre_pids: set[int],
    *,
    timeout: float,
    interval: float,
) -> int | None:
    """Return the first PID that appears after spawn relative to ``pre_pids``.

    :func:`find_pids` returns newest-first, so when more than one new PID
    appears (rare; usually only one) we take the most recent — defensive
    against a race where a sibling instance starts in the same window.
    """
    # Deferred to break the ``process/__init__.py`` <-> ``launch.py`` import
    # cycle: ``__init__`` re-exports ``find_pids`` from ``pid``, which would
    # otherwise be observed mid-construction.
    from . import find_pids

    deadline = time.monotonic() + timeout
    while True:
        current = find_pids()
        new_pids = [p for p in current if p not in pre_pids]
        if new_pids:
            return new_pids[0]
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def launch(
    *,
    via_steam: bool = False,
    app_id: int = VRCHAT_STEAM_APP_ID,
    steam_path: Path | None = None,
    vrchat_launcher: Path | None = None,
    wineprefix: Path | None = None,
    proton_path: Path | None = None,
    profile: int | None = None,
    no_vr: bool = False,
    screen_width: int | None = None,
    screen_height: int | None = None,
    osc: OscConfig | None = None,
    extra_args: list[str] | None = None,
    wait_timeout: float = PID_WAIT_TIMEOUT,
    wait_interval: float = PID_WAIT_INTERVAL,
) -> int | None:
    """Spawn VRChat and (optionally) wait for the new PID to appear.

    Two spawn routes share this entry point. The mental model:

    * **Direct-spawn (default)**: invoke the EAC wrapper ``launch.exe``
      ourselves. On Windows that is a plain ``subprocess.Popen``; on Linux
      it goes through ``umu-run`` (auto-discovered from PATH) so Proton's
      Wine prefix hosts the binary. The process is detached
      (``CREATE_NEW_PROCESS_GROUP`` / ``start_new_session=True``) and its
      stdin/stdout/stderr are redirected to ``DEVNULL`` so the caller can
      exit (and any pipes the caller installed are released) without
      taking VRChat down.
    * **Via-Steam (``via_steam=True``)**: hand off to
      ``steam.exe -applaunch <app_id>``. Refuses to run if any VRChat
      process is already up — Steam silently refocuses the existing
      instance in that case, so the call would observe no new PID and
      hang on the post-spawn wait.

    The post-spawn wait diffs ``find_pids()`` against the pre-spawn
    snapshot rather than tailing a single subprocess; this is what makes
    the via-Steam route observable at all (the spawned child is Steam's,
    not ours).

    Args:
        via_steam: Switch to the ``steam.exe -applaunch`` route. Mutually
            exclusive with ``wineprefix`` / ``proton_path`` / ``profile``
            because Steam carries those through its own launch-options UI.
        app_id: Forwarded to ``-applaunch`` on the via-Steam route only.
            Deliberately **not** exported as ``$GAMEID`` to ``umu-run`` on
            the direct-spawn route: doing so makes umu-launcher apply its
            "global defaults" protonfix (no VRChat-specific fix is
            registered upstream), which in turn pulls in an unimplemented
            ``coremessaging.dll`` entry point and aborts Wine. See the
            in-function comment for the 2026-05-23 incident reference.
        steam_path: Skip Steam auto-detection. Honoured only when
            ``via_steam=True``.
        vrchat_launcher: Skip ``launch.exe`` auto-detection. When
            ``None`` the path is resolved via
            :func:`vrcpilot.process.executable.find_vrchat_launcher`
            (Steam ``libraryfolders.vdf`` walk).
        wineprefix: Linux + direct-spawn only. Sets ``$WINEPREFIX`` for
            the ``umu-run`` child so the caller can pin a specific Wine
            prefix (e.g. one shared with Steam's ``compatdata/438100``).
        proton_path: Linux + direct-spawn only. Sets ``$PROTON_PATH`` for
            umu-launcher to consume.
        profile: VRChat ``--profile=N`` (slot number; non-negative).
            Separates SaveData / cache folders. On Linux this also seeds
            a per-profile Wine prefix under
            ``$XDG_DATA_HOME/vrcpilot/profiles/<profile>/wineprefix``
            (or ``~/.local/share/...``) unless ``wineprefix`` is set
            explicitly.
        no_vr, screen_width, screen_height, osc, extra_args: Forwarded
            verbatim to :func:`build_vrchat_launch_args`.
        wait_timeout: Seconds to wait for the new VRChat PID after
            spawning. ``<= 0`` skips the wait (returns ``None`` immediately).
        wait_interval: Poll cadence during the PID wait.

    Returns:
        The newly-spawned VRChat PID, or ``None`` when the wait was
        skipped (``wait_timeout <= 0``) or expired without observing
        a new process.

    Raises:
        ValueError: ``validate_launch_args`` rejected the argument
            combination (e.g. ``profile`` together with ``via_steam``).
        SteamNotFoundError: ``via_steam=True`` but no Steam executable
            could be located.
        SteamNotRunningError: Linux + ``via_steam=True`` but the Steam
            desktop client is not running, so ``-applaunch`` has nothing
            to dispatch to.
        VRChatLauncherNotFoundError: Direct-spawn route but ``launch.exe``
            cannot be located in any Steam library.
        UmuLauncherNotFoundError: Linux direct-spawn route but
            ``umu-run`` is missing from PATH (umu-launcher not installed).
        VRChatDisplayNotAvailableError: Linux direct-spawn route with
            neither ``$DISPLAY`` nor ``$WAYLAND_DISPLAY`` set — Wine
            would block indefinitely waiting for a graphical session.
        VRChatAlreadyRunningError: ``via_steam=True`` but at least one
            VRChat process is already running (Steam would just refocus
            it).
    """
    # Deferred so tests that monkeypatch ``vrcpilot.steam.find_steam_executable``
    # actually intercept the call — a module-level import would freeze the
    # original reference at import time.
    from vrcpilot.steam import find_steam_executable

    from .executable import find_vrchat_launcher

    validate_launch_args(
        via_steam=via_steam,
        wineprefix=wineprefix,
        proton_path=proton_path,
        profile=profile,
    )
    if sys.platform == "linux":
        from .linux import preflight_linux_environment

        preflight_linux_environment(via_steam=via_steam)

    vrchat_args = build_vrchat_launch_args(
        no_vr=no_vr,
        screen_width=screen_width,
        screen_height=screen_height,
        osc=osc,
        profile=profile,
        extra_args=extra_args,
    )

    pre_pids: set[int] = set(find_pids())

    env_overrides: dict[str, str] = {}
    if via_steam:
        if pre_pids:
            raise VRChatAlreadyRunningError(
                "via_steam=True cannot reliably launch a new instance when "
                f"VRChat is already running (existing PIDs: {sorted(pre_pids)}); "
                "steam.exe -applaunch will refocus the existing instance"
            )
        steam_executable = find_steam_executable(steam_path)
        argv = build_launch_command(steam_executable, app_id, vrchat_args=vrchat_args)
    else:
        launcher = find_vrchat_launcher(vrchat_launcher)
        if sys.platform == "win32":
            argv = [str(launcher), *vrchat_args]
        elif sys.platform == "linux":
            from .linux import find_umu_launcher, profile_wineprefix

            umu_run = find_umu_launcher()
            argv = [str(umu_run), str(launcher), *vrchat_args]
            # GAMEID is deliberately omitted. Passing GAMEID=438100 makes
            # umu-launcher apply its "global defaults" protonfix (no VRChat
            # entry is registered upstream), which calls the unimplemented
            # ``coremessaging.dll.DllGetActivationFactory`` and aborts Wine
            # (observed on hardware 2026-05-23). Without GAMEID umu falls
            # back to its bare default and boots cleanly. Worth revisiting
            # only once VRChat (438100) gains a real ProtonFixes entry.
            if wineprefix is not None:
                env_overrides["WINEPREFIX"] = str(wineprefix)
            elif profile is not None:
                generated = profile_wineprefix(profile)
                generated.mkdir(parents=True, exist_ok=True)
                env_overrides["WINEPREFIX"] = str(generated)
            if proton_path is not None:
                env_overrides["PROTON_PATH"] = str(proton_path)
        else:
            raise NotImplementedError(
                f"launch() (direct spawn) is not supported on {sys.platform}"
            )

    popen_env: dict[str, str] | None = (
        {**os.environ, **env_overrides} if env_overrides else None
    )

    # stdout/stderr are routed to DEVNULL so the grandchild (umu-run / Wine /
    # launch.exe) does not inherit whatever fds the caller of ``vrcpilot
    # launch`` happened to install. The concrete failure this avoids: a parent
    # using ``subprocess.run(..., capture_output=True)`` hands the CLI a
    # pipe; the CLI exits after printing the PID but ``umu-run`` keeps the
    # pipe's write end open and chatters Wine logs into it, so the parent's
    # ``subprocess.run`` blocks on EOF forever (observed by the e2e harness
    # in cli_launch_terminate.py on 2026-05-24).
    if sys.platform == "win32":
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=popen_env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=popen_env,
            start_new_session=True,
        )

    if wait_timeout <= 0:
        return None
    return _wait_for_new_pid(pre_pids, timeout=wait_timeout, interval=wait_interval)
