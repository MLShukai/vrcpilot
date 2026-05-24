"""``vrcpilot unfocus`` subcommand: drop the VRChat window in the z-order.

Thin shell over :func:`vrcpilot.window.unfocus`. The same failure
surface as ``focus`` (no VRChat, no window, native Wayland) collapses
to a single user-visible diagnostic.
"""

from __future__ import annotations

import argparse
import sys

from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.window import unfocus

from ._common import SubParsersAction, add_pid_arg, handle_multi_instance_error


def register(subparsers: SubParsersAction) -> None:
    """Wire the ``unfocus`` subparser into the top-level CLI."""
    parser = subparsers.add_parser(
        "unfocus",
        help="Send the running VRChat window to the bottom of the z-order.",
    )
    add_pid_arg(parser)


def run(args: argparse.Namespace) -> int:
    """Drop the VRChat window in z-order; silent on success.

    Exit codes:

    * 0: window was sent to the bottom
    * 1: any failure (no VRChat, no window, native Wayland, or the
      multi-instance case without ``--pid``); a single
      ``vrcpilot: ...`` line is written to stderr.
    """
    try:
        if unfocus(pid=args.pid):
            return 0
    except VRChatMultipleInstancesError as exc:
        handle_multi_instance_error(exc)
        return 1
    print("vrcpilot: could not unfocus VRChat", file=sys.stderr)
    return 1
