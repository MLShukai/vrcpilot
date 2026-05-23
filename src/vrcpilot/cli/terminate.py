"""``vrcpilot terminate`` subcommand."""

from __future__ import annotations

import argparse
import sys

from vrcpilot.process import terminate

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Add the ``terminate`` subparser to the top-level subparsers."""
    parser = subparsers.add_parser(
        "terminate",
        help=(
            "Forcefully terminate VRChat processes. Without arguments, "
            "kills every running VRChat process. With PIDs, kills only those."
        ),
    )
    parser.add_argument(
        "pids",
        nargs="*",
        type=int,
        metavar="PID",
        help=(
            "VRChat PIDs to kill. When omitted, every running VRChat process is killed."
        ),
    )


def run(args: argparse.Namespace) -> int:
    """Kill specified PIDs (or all when none given); idempotent.

    Killed PIDs print one per line on stdout; the no-op path stays
    silent so consumers can pipe through ``xargs`` safely. Exit 1 when
    :func:`vrcpilot.process.terminate` rejects a non-VRChat PID with
    :class:`ValueError`.
    """
    pids: list[int] = args.pids
    try:
        killed = terminate(*pids)
    except ValueError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    for pid in killed:
        print(pid)
    return 0
