"""``vrcpilot pid`` subcommand."""

from __future__ import annotations

import argparse

from vrcpilot.process import find_pids

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Add the ``pid`` subparser to the top-level subparsers."""
    subparsers.add_parser(
        "pid",
        help="Print PIDs of running VRChat processes (one per line).",
    )


def run(args: argparse.Namespace) -> int:
    """Print live VRChat PIDs; exit 1 (with empty stdout) when none run.

    State-dependent exit lets shells branch with
    ``if vrcpilot pid >/dev/null; then ...``.
    """
    del args
    pids = find_pids()
    if not pids:
        return 1
    for pid in pids:
        print(pid)
    return 0
