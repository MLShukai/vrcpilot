"""``vrcpilot mouse`` subcommand: synthetic mouse input into VRChat.

Exposes ``move`` / ``click`` / ``scroll``. ``press`` / ``release``
are intentionally not exposed because each CLI invocation owns its
own ``/dev/uinput`` device on Linux and the kernel auto-releases held
buttons when that device closes — so a held button cannot survive
across processes (same trade-off as :mod:`vrcpilot.cli.keyboard`).

Tests bind fakes by patching :data:`mouse_api`; preserve that import
alias when refactoring.
"""

from __future__ import annotations

import argparse
import sys

from vrcpilot.controls import (
    VRChatNotFocusedError,
    mouse as mouse_api,
)
from vrcpilot.controls.mouse import MouseButton
from vrcpilot.process import VRChatMultipleInstancesError, VRChatNotRunningError

from ._common import SubParsersAction, add_pid_arg, handle_multi_instance_error


def register(subparsers: SubParsersAction) -> None:
    """Wire ``mouse`` plus its three action sub-subcommands into the CLI."""
    parser = subparsers.add_parser(
        "mouse",
        help="Synthetic mouse input (move / click / scroll; press/release "
        "are not exposed because cross-invocation hold is unsupported).",
    )
    actions = parser.add_subparsers(dest="mouse_action", required=True)

    move_parser = actions.add_parser(
        "move",
        help=(
            "Move the cursor to (X, Y) in VRChat window-local pixels, "
            "or by (X, Y) deltas with --rel."
        ),
    )
    move_parser.add_argument("x", type=int)
    move_parser.add_argument("y", type=int)
    move_parser.add_argument(
        "--rel",
        action="store_true",
        help="Treat X and Y as relative deltas instead of VRChat window-local pixels.",
    )
    add_pid_arg(move_parser)

    click_parser = actions.add_parser(
        "click",
        help="Click one or more mouse buttons simultaneously (default: left).",
    )
    click_parser.add_argument(
        "button",
        nargs="*",
        type=MouseButton,
        default=[],
        help=(
            "Click one or more mouse buttons simultaneously "
            "(default: left). Values: left / right / middle."
        ),
    )
    click_parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of click cycles. Default: 1.",
    )
    click_parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Down-to-up hold per click cycle, in seconds. Default: 0.0.",
    )
    click_parser.add_argument(
        "--interval",
        type=float,
        default=0.0,
        help=(
            "Inter-cycle gap between click cycles, in seconds. Use "
            "0.02 - 0.05 for VRChat double-click on Linux (inputtino + "
            "Wine). Default: 0.0."
        ),
    )
    add_pid_arg(click_parser)

    scroll_parser = actions.add_parser(
        "scroll",
        help="Scroll vertically by AMOUNT notches (positive = down).",
    )
    scroll_parser.add_argument("amount", type=int)
    add_pid_arg(scroll_parser)


def run(args: argparse.Namespace) -> int:
    """Dispatch ``mouse {move,click,scroll}``; silent on success.

    Exit 1 with ``vrcpilot: ...`` on stderr when the focus guard fires
    (VRChat not running / not focused) or the multi-instance case
    triggers without ``--pid``.
    """
    try:
        match args.mouse_action:
            case "move":
                mouse_api.move(args.x, args.y, relative=args.rel, pid=args.pid)
            case "click":
                mouse_api.click(
                    *args.button,
                    count=args.count,
                    duration=args.duration,
                    interval=args.interval,
                    pid=args.pid,
                )
            case "scroll":
                mouse_api.scroll(args.amount, pid=args.pid)
            case _:  # pragma: no cover - argparse required=True prevents this
                raise AssertionError(f"Unknown mouse action: {args.mouse_action!r}")
    except VRChatMultipleInstancesError as exc:
        # Subclass of VRChatNotRunningError -- match it first so the
        # tailored multi-instance diagnostic wins.
        handle_multi_instance_error(exc)
        return 1
    except (VRChatNotRunningError, VRChatNotFocusedError) as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    return 0
