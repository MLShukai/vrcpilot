"""``vrcpilot mouse`` subcommand.

Thin CLI wrapper over :mod:`vrcpilot.controls.mouse`. Exposes
``move`` / ``click`` / ``scroll`` -- all stateless one-shot actions
that complete inside a single CLI invocation. ``press`` / ``release``
are intentionally NOT exposed: each ``vrcpilot`` process opens and
closes its own backend (``/dev/uinput`` on Linux), and the kernel
auto-releases all held buttons when the virtual device is destroyed,
so a separate ``press`` and ``release`` invocation cannot keep a
button held. Mirrors the same trade-off applied to ``keyboard``
(only ``press`` is exposed there for the same reason).

The :data:`mouse_api` alias below is a stable patch target: tests bind
their fakes by patching ``vrcpilot.controls.mouse._get`` so the real
public ``mouse.move`` / ``mouse.click`` / ``mouse.scroll`` flow through
to a recording :class:`~vrcpilot.controls.mouse.Mouse` impl.
"""

from __future__ import annotations

import argparse
import sys

from vrcpilot.controls import (
    VRChatNotFocusedError,
    VRChatNotRunningError,
    mouse as mouse_api,
)
from vrcpilot.controls.mouse import MouseButton

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Add the ``mouse`` subparser plus its three action sub-subcommands."""
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

    scroll_parser = actions.add_parser(
        "scroll",
        help="Scroll vertically by AMOUNT notches (positive = down).",
    )
    scroll_parser.add_argument("amount", type=int)


def run(args: argparse.Namespace) -> int:
    """Execute the ``mouse`` subcommand.

    Silent on success. Guard failures (VRChat not running / not focused)
    print a single ``vrcpilot: <message>`` line to stderr and return
    exit 1. The action dispatch uses ``args.mouse_action`` set by the
    sub-subparser.

    Returns:
        ``0`` on success, ``1`` on guard failure.
    """
    try:
        match args.mouse_action:
            case "move":
                mouse_api.move(args.x, args.y, relative=args.rel)
            case "click":
                mouse_api.click(*args.button, count=args.count, duration=args.duration)
            case "scroll":
                mouse_api.scroll(args.amount)
            case _:  # pragma: no cover - argparse required=True prevents this
                raise AssertionError(f"Unknown mouse action: {args.mouse_action!r}")
    except (VRChatNotRunningError, VRChatNotFocusedError) as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    return 0
