"""``vrcpilot focus`` subcommand: bring the VRChat window to the foreground.

Thin shell over :func:`vrcpilot.window.focus`. The window backend can
fail for several reasons (no VRChat, no window handle, native Wayland)
that all collapse to a single user-visible diagnostic.
"""

from __future__ import annotations

import argparse
import sys

from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.window import focus

from ._common import SubParsersAction, add_pid_arg, handle_multi_instance_error


def register(subparsers: SubParsersAction) -> None:
    """Wire the ``focus`` subparser into the top-level CLI."""
    parser = subparsers.add_parser(
        "focus",
        help="Bring the running VRChat window to the foreground.",
    )
    add_pid_arg(parser)


def run(args: argparse.Namespace) -> int:
    """Focus the VRChat window; silent on success.

    Exit codes:

    * 0: window was focused
    * 1: any failure (no VRChat, no window, native Wayland, or the
      multi-instance case without ``--pid``); a single
      ``vrcpilot: ...`` line is written to stderr.
    """
    try:
        if focus(pid=args.pid):
            return 0
    except VRChatMultipleInstancesError as exc:
        handle_multi_instance_error(exc)
        return 1
    print("vrcpilot: could not focus VRChat", file=sys.stderr)
    return 1
