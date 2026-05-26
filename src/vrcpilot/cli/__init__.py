# PYTHON_ARGCOMPLETE_OK
"""Entry point for the ``vrcpilot`` console script and ``python -m vrcpilot``.

Each subcommand module exposes a ``register(subparsers)`` /
``run(args) -> int`` pair; this module wires them together and routes
the parsed namespace back to the matching ``run``.
"""

from __future__ import annotations

import argparse
import sys
from importlib import metadata
from types import ModuleType

import argcomplete

from . import (
    detect,
    focus,
    keyboard,
    launch,
    mic,
    mouse,
    ocr,
    osc,
    paste,
    pid,
    record,
    screenshot,
    speaker_device,
    terminate,
    unfocus,
)

_COMMANDS: dict[str, ModuleType] = {
    "launch": launch,
    "pid": pid,
    "terminate": terminate,
    "focus": focus,
    "unfocus": unfocus,
    "screenshot": screenshot,
    "record": record,
    "mic": mic,
    "speaker-device": speaker_device,
}

# ``linux-mic`` slots between ``mic`` and ``mouse`` on Linux so the
# original help ordering is preserved; argcomplete and ``--help`` both
# iterate ``_COMMANDS`` in insertion order.
if sys.platform == "linux":
    from . import linux_mic

    _COMMANDS["linux-mic"] = linux_mic

_COMMANDS.update(
    {
        "mouse": mouse,
        "keyboard": keyboard,
        "paste": paste,
        "ocr": ocr,
        "osc": osc,
        "detect": detect,
    }
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with every subcommand pre-registered.

    Exposed so tests and ``argcomplete`` can inspect the parser
    without executing any command.
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
    """Parse ``argv`` and dispatch to the matching subcommand's ``run``.

    Returns the subcommand's exit code instead of calling
    :func:`sys.exit` so tests can drive ``main`` in-process.
    """
    parser = build_parser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    return _COMMANDS[args.command].run(args)


__all__ = ["main"]
