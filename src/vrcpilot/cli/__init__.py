# PYTHON_ARGCOMPLETE_OK
"""Entry point for the ``vrcpilot`` console script and ``python -m vrcpilot``.

Each subcommand module exposes a ``register(subparsers)`` /
``run(args) -> int`` pair; this module just wires them together.
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
}

# ``linux-mic`` is registered between ``mic`` and ``mouse`` only on
# Linux. Inserting it here (rather than appending) preserves the
# original ``vrcpilot --help`` ordering -- argcomplete and the help
# text iterate ``_COMMANDS`` in insertion order.
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
    """Return the fully-configured top-level parser.

    Public so tests and ``argcomplete`` can obtain it without running
    a command.
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
    """Run the ``vrcpilot`` CLI and return its exit code.

    Returns the code rather than calling :func:`sys.exit` so tests can
    drive ``main`` directly.
    """
    parser = build_parser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    return _COMMANDS[args.command].run(args)


__all__ = ["main"]
