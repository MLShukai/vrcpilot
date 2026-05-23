"""``vrcpilot paste`` subcommand: clipboard + Ctrl+V into VRChat.

Text comes from the positional arg or piped stdin (the stdin fallback
avoids shell-quoting hassles for multi-line text). Exit codes: 0 ok, 1
guard or clipboard backend failure, 2 no text supplied (positional
omitted and stdin is a tty, where reading would block forever).
"""

from __future__ import annotations

import argparse
import sys

import pyperclip

from vrcpilot import clipboard
from vrcpilot.controls import VRChatNotFocusedError
from vrcpilot.process import VRChatNotRunningError

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Add the ``paste`` subparser to the top-level subparsers."""
    parser = subparsers.add_parser(
        "paste",
        help=(
            "Copy text to the clipboard and send Ctrl+V to VRChat. "
            "Reads from stdin when TEXT is omitted and stdin is piped."
        ),
    )
    parser.add_argument(
        "text",
        nargs="?",
        default=None,
        metavar="TEXT",
        help=(
            "Text to paste. Omit to read from stdin (only when stdin is "
            "piped; on a tty this exits with code 2)."
        ),
    )


def run(args: argparse.Namespace) -> int:
    """Execute the ``paste`` subcommand; see module docstring for exits."""
    raw: str | None = args.text
    if raw is None:
        if sys.stdin.isatty():
            print("vrcpilot: no text provided", file=sys.stderr)
            return 2
        text = sys.stdin.read()
    else:
        text = raw
    try:
        clipboard.paste(text)
    except (VRChatNotRunningError, VRChatNotFocusedError) as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    except pyperclip.PyperclipException as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    return 0
