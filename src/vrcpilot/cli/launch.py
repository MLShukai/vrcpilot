"""``vrcpilot launch`` subcommand."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from argcomplete.completers import FilesCompleter

from vrcpilot.process import (
    PID_WAIT_TIMEOUT,
    VRCHAT_STEAM_APP_ID,
    OscConfig,
    UmuLauncherNotFoundError,
    VRChatAlreadyRunningError,
    VRChatLauncherNotFoundError,
    launch,
)
from vrcpilot.steam import SteamNotFoundError

from ._common import SubParsersAction, attach_completer


def _profile_value(value: str) -> int:
    """Argparse ``type`` validator for ``--profile``.

    Parses ``value`` as an integer and rejects negatives so the
    vrcpilot-managed prefix index is always ``>= 0``. Raises
    :class:`argparse.ArgumentTypeError` with a clear message so argparse
    can surface it as an exit-2 usage error.
    """
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"profile must be non-negative (got {parsed})")
    return parsed


def register(subparsers: SubParsersAction) -> None:
    """Add the ``launch`` subparser to the top-level subparsers.

    The default launch route spawns VRChat's ``launch.exe`` directly
    (via ``umu-run`` on Linux). Pass ``--via-steam`` to fall back to the
    legacy ``steam.exe -applaunch`` path. ``--wineprefix`` / ``--proton-path``
    / ``--profile`` are Linux + direct-spawn only and conflict with
    ``--via-steam``.
    """
    launch_parser = subparsers.add_parser(
        "launch",
        help="Launch VRChat (direct spawn by default; --via-steam for Steam route).",
    )
    launch_parser.add_argument(
        "--via-steam",
        action="store_true",
        help=(
            "Use the legacy ``steam.exe -applaunch <app_id>`` route instead "
            "of spawning ``launch.exe`` directly. Fails fast if VRChat is "
            "already running."
        ),
    )
    launch_parser.add_argument(
        "--app-id",
        type=int,
        default=VRCHAT_STEAM_APP_ID,
        help="Steam app id to launch (default: VRChat's app id).",
    )
    steam_path_action = launch_parser.add_argument(
        "--steam-path",
        type=Path,
        default=None,
        help="Override the auto-detected Steam executable path (only with --via-steam).",
    )
    attach_completer(
        steam_path_action, FilesCompleter(allowednames=("exe",), directories=True)
    )
    vrchat_launcher_action = launch_parser.add_argument(
        "--vrchat-launcher",
        type=Path,
        default=None,
        help=("Override the auto-detected ``launch.exe`` (VRChat EAC wrapper) path."),
    )
    attach_completer(vrchat_launcher_action, FilesCompleter(directories=True))
    wineprefix_action = launch_parser.add_argument(
        "--wineprefix",
        type=Path,
        default=None,
        help=(
            "Linux + direct-spawn only. Override ``$WINEPREFIX`` for the "
            "umu-run subprocess."
        ),
    )
    attach_completer(wineprefix_action, FilesCompleter(directories=True))
    proton_path_action = launch_parser.add_argument(
        "--proton-path",
        type=Path,
        default=None,
        help=(
            "Linux + direct-spawn only. Override ``$PROTON_PATH`` for the "
            "umu-run subprocess."
        ),
    )
    attach_completer(proton_path_action, FilesCompleter(directories=True))
    launch_parser.add_argument(
        "--profile",
        type=_profile_value,
        default=None,
        metavar="N",
        help=(
            "Linux + direct-spawn only. Use a vrcpilot-managed wineprefix at "
            "``$XDG_DATA_HOME/vrcpilot/profiles/<N>/wineprefix``. Must be a "
            "non-negative integer. Overridden by an explicit --wineprefix."
        ),
    )
    launch_parser.add_argument(
        "--no-vr",
        action="store_true",
        help="Force desktop mode (passes --no-vr to VRChat).",
    )
    launch_parser.add_argument(
        "--screen-width",
        type=int,
        default=None,
        help="Window width passed to Unity as -screen-width.",
    )
    launch_parser.add_argument(
        "--screen-height",
        type=int,
        default=None,
        help="Window height passed to Unity as -screen-height.",
    )
    launch_parser.add_argument(
        "--osc-in-port",
        type=int,
        default=None,
        help=(
            "OSC inbound port. When set, OSC config (including --osc-out-ip "
            "and --osc-out-port) is forwarded to VRChat. When unset, all "
            "--osc-out-* flags are ignored."
        ),
    )
    launch_parser.add_argument(
        "--osc-out-ip",
        type=str,
        default="127.0.0.1",
        help="OSC outbound IP. Only meaningful with --osc-in-port (default 127.0.0.1).",
    )
    launch_parser.add_argument(
        "--osc-out-port",
        type=int,
        default=9001,
        help="OSC outbound port. Only meaningful with --osc-in-port (default 9001).",
    )
    launch_parser.add_argument(
        "--wait-timeout",
        type=float,
        default=PID_WAIT_TIMEOUT,
        help=(
            "Seconds to wait for VRChat to appear after launch. "
            f"Default {PID_WAIT_TIMEOUT}. Pass 0 (or any non-positive "
            "value) to skip the wait and exit immediately after spawning."
        ),
    )


def run(args: argparse.Namespace) -> int:
    """Run ``launch``; print the PID on stdout when a wait succeeds.

    ``osc_in_port`` gates the OSC triple: without it the other
    ``--osc-out-*`` flags are silently ignored. ``--wait-timeout 0`` (or
    negative) spawns and returns without waiting.

    Exit codes:

    * 0: success (PID printed) or wait was skipped
    * 1: wait timed out without observing a new PID
    * 2: Steam/launch.exe/umu-run not found, or invalid flag combination
    * 3: :class:`VRChatAlreadyRunningError` was raised (currently only
      reachable via the ``--via-steam`` route)
    """
    osc = (
        OscConfig(
            in_port=args.osc_in_port,
            out_ip=args.osc_out_ip,
            out_port=args.osc_out_port,
        )
        if args.osc_in_port is not None
        else None
    )
    timeout: float = args.wait_timeout
    try:
        pid = launch(
            via_steam=args.via_steam,
            app_id=args.app_id,
            steam_path=args.steam_path,
            vrchat_launcher=args.vrchat_launcher,
            wineprefix=args.wineprefix,
            proton_path=args.proton_path,
            profile=args.profile,
            no_vr=args.no_vr,
            screen_width=args.screen_width,
            screen_height=args.screen_height,
            osc=osc,
            wait_timeout=timeout,
        )
    except (
        ValueError,
        SteamNotFoundError,
        UmuLauncherNotFoundError,
        VRChatLauncherNotFoundError,
    ) as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 2
    except VRChatAlreadyRunningError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 3

    if pid is None:
        if timeout <= 0:
            return 0
        print(
            f"vrcpilot: VRChat did not start within {timeout}s",
            file=sys.stderr,
        )
        return 1
    print(pid, flush=True)
    return 0
