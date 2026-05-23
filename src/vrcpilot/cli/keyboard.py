"""``vrcpilot keyboard`` subcommand (``press`` only).

Only ``press`` is exposed because each CLI invocation owns its own
``/dev/uinput`` device on Linux and the kernel auto-releases all
held keys when that device closes — so a separate ``down`` / ``up``
across processes cannot keep a key held.
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
    """Add the ``keyboard`` subparser plus the ``press`` sub-subcommand."""
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
    """Run ``keyboard press``; silent on success, exit 1 on guard failure.

    All keys are pressed simultaneously: down left-to-right, single
    ``duration`` sleep, up right-to-left.
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
