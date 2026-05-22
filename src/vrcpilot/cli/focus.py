"""``vrcpilot focus`` subcommand."""

from __future__ import annotations

import argparse
import sys

from vrcpilot.window import focus

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Add the ``focus`` subparser to the top-level subparsers."""
    subparsers.add_parser(
        "focus",
        help="Bring the running VRChat window to the foreground.",
    )


def run(args: argparse.Namespace) -> int:
    """Run ``focus``; silent on success, exit 1 on any failure.

    Failures (VRChat not running, no window, native Wayland) print one
    ``vrcpilot: ...`` line to stderr.
    """
    del args
    if focus():
        return 0
    print("vrcpilot: could not focus VRChat", file=sys.stderr)
    return 1
