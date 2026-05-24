"""``vrcpilot pid`` subcommand: enumerate live VRChat PIDs.

The state-dependent exit code (1 when no VRChat is running) is the
useful signal — shells branch with
``if vrcpilot pid >/dev/null; then ...`` rather than parsing stdout.
"""

from __future__ import annotations

import argparse

from vrcpilot.process import find_pids

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Wire the ``pid`` subparser into the top-level CLI."""
    subparsers.add_parser(
        "pid",
        help="Print PIDs of running VRChat processes (one per line).",
    )


def run(args: argparse.Namespace) -> int:
    """List live VRChat PIDs (one per line); exit 1 when none are running.

    The "no VRChat" path is intentionally silent on both stdout and
    stderr so the exit code remains the sole signal callers branch on.
    """
    del args
    pids = find_pids()
    if not pids:
        return 1
    for pid in pids:
        print(pid)
    return 0
