"""``vrcpilot unfocus`` subcommand."""

from __future__ import annotations

import argparse
import sys

from vrcpilot.window import unfocus

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Add the ``unfocus`` subparser to the top-level subparsers."""
    subparsers.add_parser(
        "unfocus",
        help="Send the running VRChat window to the bottom of the z-order.",
    )


def run(args: argparse.Namespace) -> int:
    """Run ``unfocus``; silent on success, exit 1 on any failure.

    Failures (VRChat not running, no window, native Wayland) print one
    ``vrcpilot: ...`` line to stderr.
    """
    del args
    if unfocus():
        return 0
    print("vrcpilot: could not unfocus VRChat", file=sys.stderr)
    return 1
