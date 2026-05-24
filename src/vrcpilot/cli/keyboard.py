"""``vrcpilot keyboard`` subcommand: synthetic key input into VRChat.

Only ``press`` is exposed. A separate ``down`` / ``up`` across CLI
invocations cannot keep a key held because each invocation owns its
own ``/dev/uinput`` device on Linux and the kernel auto-releases all
held keys when that device closes.

Tests bind fakes by patching :data:`keyboard_api`; preserve that
import alias when refactoring.
"""

from __future__ import annotations

import argparse
import sys

from vrcpilot.controls import (
    VRChatNotFocusedError,
    keyboard as keyboard_api,
)
from vrcpilot.controls.keyboard import Key
from vrcpilot.process import VRChatMultipleInstancesError, VRChatNotRunningError

from ._common import SubParsersAction, add_pid_arg, handle_multi_instance_error


def register(subparsers: SubParsersAction) -> None:
    """Wire the ``keyboard`` subparser and its ``press`` action into the
    CLI."""
    parser = subparsers.add_parser(
        "keyboard",
        help="Synthetic keyboard input (press only; held-state across "
        "invocations is not supported by the CLI).",
    )
    actions = parser.add_subparsers(dest="keyboard_action", required=True)

    press_parser = actions.add_parser(
        "press",
        help="Tap one or more keys (down then up, simultaneously).",
    )
    press_parser.add_argument(
        "keys",
        nargs="+",
        type=Key,
        metavar="KEY",
        help="One or more Key enum values (e.g. a, ctrl, escape, f1).",
    )
    press_parser.add_argument(
        "--duration",
        type=float,
        default=0.1,
        help="Down-to-up hold per key, in seconds. Default: 0.1.",
    )
    add_pid_arg(press_parser)


def run(args: argparse.Namespace) -> int:
    """Tap the requested keys simultaneously; silent on success.

    Press order is deterministic: down left-to-right, single
    ``duration`` sleep, then up right-to-left — matching the order
    VRChat / Unity expect for modifier-first chords.

    Exit 1 with ``vrcpilot: ...`` on stderr when the focus guard fires
    or the multi-instance case triggers without ``--pid``.
    """
    keys: list[Key] = args.keys
    duration: float = args.duration
    try:
        keyboard_api.press(*keys, duration=duration, pid=args.pid)
    except VRChatMultipleInstancesError as exc:
        # Subclass of VRChatNotRunningError -- handle the multi-instance
        # case explicitly so the user is pointed at ``--pid``.
        handle_multi_instance_error(exc)
        return 1
    except (VRChatNotRunningError, VRChatNotFocusedError) as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    return 0
