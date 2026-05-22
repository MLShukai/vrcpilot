"""``vrcpilot terminate`` subcommand."""

from __future__ import annotations

import argparse

from vrcpilot.process import terminate

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Add the ``terminate`` subparser to the top-level subparsers."""
    subparsers.add_parser(
        "terminate",
        help="Forcefully terminate any running VRChat process.",
    )


def run(args: argparse.Namespace) -> int:
    """Kill any running VRChat process; idempotent (always exits 0).

    Killed PIDs print one per line on stdout; the no-op path stays
    silent so consumers can pipe through ``xargs`` safely.
    """
    del args
    for pid in terminate():
        print(pid)
    return 0
