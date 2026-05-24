"""``vrcpilot terminate`` subcommand: force-kill VRChat processes.

Idempotent: killing a vanished PID or running with no targets is exit
0 and silent so callers can pipe through ``xargs`` without filtering
noise.
"""

from __future__ import annotations

import argparse
import sys

from vrcpilot.process import terminate

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Wire the ``terminate`` subparser into the top-level CLI."""
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
    """Kill the requested PIDs (or all running VRChat when none given).

    Killed PIDs print one per line on stdout; the no-op path stays
    silent so the output is safe to pipe through ``xargs``. Exit 1
    with ``vrcpilot: ...`` on stderr when
    :func:`vrcpilot.process.terminate` rejects a non-VRChat PID — the
    guard that prevents users from killing arbitrary processes.
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
