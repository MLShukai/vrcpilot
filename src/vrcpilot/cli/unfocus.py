"""``vrcpilot unfocus`` subcommand."""

from __future__ import annotations

import argparse
import sys

from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.window import unfocus

from ._common import SubParsersAction, add_pid_arg, handle_multi_instance_error


def register(subparsers: SubParsersAction) -> None:
    """Add the ``unfocus`` subparser to the top-level subparsers."""
    parser = subparsers.add_parser(
        "unfocus",
        help="Send the running VRChat window to the bottom of the z-order.",
    )
    add_pid_arg(parser)


def run(args: argparse.Namespace) -> int:
    """Run ``unfocus``; silent on success, exit 1 on any failure.

    Failures (VRChat not running, no window, native Wayland) print one
    ``vrcpilot: ...`` line to stderr. With multiple VRChat processes
    running and no ``--pid``, exits 1 with the multi-instance diagnostic.
    """
    try:
        if unfocus(pid=args.pid):
            return 0
    except VRChatMultipleInstancesError as exc:
        handle_multi_instance_error(exc)
        return 1
    print("vrcpilot: could not unfocus VRChat", file=sys.stderr)
    return 1
