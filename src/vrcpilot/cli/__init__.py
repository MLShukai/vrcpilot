# PYTHON_ARGCOMPLETE_OK
"""Command line interface for vrcpilot.

Thin dispatcher that translates :mod:`argparse` invocations into
public-API calls and exit codes. Each subcommand lives in
``vrcpilot.cli.<name>`` and exposes a ``register(subparsers)`` /
``run(args) -> int`` pair. :func:`main` is the entry point for both
the ``vrcpilot`` console script and ``python -m vrcpilot``.
"""

from __future__ import annotations

import argparse
from importlib import metadata

import argcomplete

from . import (
    capture,
    detect,
    focus,
    keyboard,
    launch,
    mouse,
    ocr,
    osc,
    paste,
    pid,
    screenshot,
    terminate,
    unfocus,
)

_COMMANDS = {
    "launch": launch,
    "pid": pid,
    "terminate": terminate,
    "focus": focus,
    "unfocus": unfocus,
    "screenshot": screenshot,
    "capture": capture,
    "mouse": mouse,
    "keyboard": keyboard,
    "paste": paste,
    "ocr": ocr,
    "osc": osc,
    "detect": detect,
}


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser with all subcommands.

    Public (no ``_`` prefix) so tests and the ``argcomplete`` hook can
    obtain a fully-configured parser without running a command.
    """
    parser = argparse.ArgumentParser(
        prog="vrcpilot",
        description="Automation tooling for VRChat.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {metadata.version('vrcpilot')}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in _COMMANDS.values():
        module.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the ``vrcpilot`` CLI and return an exit code.

    Returns the code instead of calling :func:`sys.exit` so tests can
    pass ``argv`` and assert on the return value.
    """
    parser = build_parser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    return _COMMANDS[args.command].run(args)


__all__ = ["main"]
