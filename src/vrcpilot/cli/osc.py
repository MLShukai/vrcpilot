"""``vrcpilot osc`` subcommand: send VRChat OSC messages.

Seven actions (``send`` / ``axis`` / ``tap`` / ``hold`` / ``chatbox`` /
``typing`` / ``avatar``); see ``docs/cli.md`` for the full table.

Unlike ``mouse`` / ``keyboard`` there is no shared device, so
``hold <name> on`` followed by a later ``hold <name> off`` from a fresh
invocation works — every OSC action is fire-and-forget UDP.
"""

from __future__ import annotations

import argparse
import sys
from typing import Final

from vrcpilot.osc import OscSender
from vrcpilot.osc.controller import InputController

from ._common import SubParsersAction

#: Axis-style ``/input/*`` inputs (float in ``[-1.0, 1.0]``). Each
#: entry maps to the same-named :class:`InputController` method via
#: :func:`_to_method` (``-`` -> ``_``); ditto for :data:`TAP_NAMES`
#: and :data:`HOLD_NAMES`.
AXIS_NAMES: Final[tuple[str, ...]] = (
    "vertical",
    "horizontal",
    "look-horizontal",
    "use-axis-right",
    "grab-axis-right",
    "move-hold-fb",
    "spin-hold-cw-ccw",
    "spin-hold-ud",
    "spin-hold-lr",
)

#: Tap-style ``/input/*`` buttons (``1`` -> sleep -> ``0``).
TAP_NAMES: Final[tuple[str, ...]] = (
    "jump",
    "voice",
    "panic",
    "quick-menu-toggle-left",
    "quick-menu-toggle-right",
    "drop-left",
    "drop-right",
    "comfort-left",
    "comfort-right",
)

#: Hold-style ``/input/*`` buttons (explicit on/off).
HOLD_NAMES: Final[tuple[str, ...]] = (
    "run",
    "hold-voice",
    "move-forward",
    "move-backward",
    "move-left",
    "move-right",
    "look-left",
    "look-right",
    "use-left",
    "use-right",
    "grab-left",
    "grab-right",
)


#: Accepted ``--bool`` choices for ``send`` and ``avatar``.
_BOOL_CHOICES: Final[tuple[str, ...]] = ("true", "false", "1", "0")


def _to_method(name: str) -> str:
    """Map a kebab-case CLI choice to its :class:`InputController` method."""
    return name.replace("-", "_")


def _parse_bool_str(value: str) -> bool:
    """Convert one of :data:`_BOOL_CHOICES` to a ``bool`` (``send`` /
    ``avatar``)."""
    return value in ("true", "1")


def _make_sender(host: str, port: int) -> OscSender:
    """Construct the :class:`OscSender` that ``run()`` dispatches through.

    Stable patch target so tests can swap in a fake UDP client while
    still exercising the real validation path.
    """
    return OscSender(host=host, port=port)


def _make_controller(args: argparse.Namespace) -> InputController:
    """Build a fresh :class:`InputController` from the shared parent flags."""
    return _make_sender(args.host, args.port).controller(button_hold=args.button_hold)


def register(subparsers: SubParsersAction) -> None:
    """Wire ``osc`` and its seven action sub-subcommands into the CLI.

    Choices for ``axis`` / ``tap`` / ``hold`` come from
    :data:`AXIS_NAMES` / :data:`TAP_NAMES` / :data:`HOLD_NAMES` — those
    tuples are the single source of truth.
    """
    parser = subparsers.add_parser(
        "osc",
        help="Send VRChat OSC messages (raw send, plus high-level "
        "InputController and AvatarParameters wrappers).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="OSC target host (applies to all osc actions). Default: 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="OSC target port (applies to all osc actions). Default: 9000.",
    )
    parser.add_argument(
        "--button-hold",
        type=float,
        default=0.05,
        help=(
            "Hold time in seconds between 1 and 0 for tap-style buttons "
            "(applies to all osc actions that tap a button). Default: 0.05."
        ),
    )

    actions = parser.add_subparsers(dest="osc_action", required=True)

    send_parser = actions.add_parser(
        "send",
        help="Send a typed OSC message to ADDRESS (--bool / --int / --float).",
    )
    send_parser.add_argument(
        "address",
        help="OSC address (e.g. /input/Jump or /avatar/parameters/MyParam).",
    )
    send_type = send_parser.add_mutually_exclusive_group(required=True)
    send_type.add_argument(
        "--bool",
        dest="bool_value",
        choices=_BOOL_CHOICES,
        help=(
            "Send as bool. Accepted values: true / false / 1 / 0. "
            "VRChat receives 0 or 1 as an int tag."
        ),
    )
    send_type.add_argument(
        "--int",
        dest="int_value",
        type=int,
        help="Send as int. Must be in [0, 255].",
    )
    send_type.add_argument(
        "--float",
        dest="float_value",
        type=float,
        help="Send as float. Must be in [-1.0, 1.0].",
    )

    axis_parser = actions.add_parser(
        "axis",
        help="Set an InputController axis to VALUE (-1.0..1.0).",
    )
    axis_parser.add_argument(
        "name",
        choices=AXIS_NAMES,
        help="Axis name (kebab-case). One of: " + ", ".join(AXIS_NAMES) + ".",
    )
    axis_parser.add_argument(
        "value",
        type=float,
        help="Axis value in [-1.0, 1.0].",
    )

    tap_parser = actions.add_parser(
        "tap",
        help="Tap an InputController button (1 -> sleep --button-hold -> 0).",
    )
    tap_parser.add_argument(
        "name",
        choices=TAP_NAMES,
        help="Tap-button name (kebab-case). One of: " + ", ".join(TAP_NAMES) + ".",
    )

    hold_parser = actions.add_parser(
        "hold",
        help="Press (on) or release (off) an InputController hold button.",
    )
    hold_parser.add_argument(
        "name",
        choices=HOLD_NAMES,
        help="Hold-button name (kebab-case). One of: " + ", ".join(HOLD_NAMES) + ".",
    )
    hold_parser.add_argument(
        "state",
        choices=("on", "off"),
        help="Press (on) or release (off).",
    )

    chatbox_parser = actions.add_parser(
        "chatbox",
        help=(
            "Post text to the in-game chatbox via /chatbox/input. "
            "Reads from stdin when TEXT is omitted and stdin is piped."
        ),
    )
    chatbox_parser.add_argument(
        "text",
        nargs="?",
        default=None,
        metavar="TEXT",
        help=(
            "Text to post. Omit to read from stdin (only when stdin is "
            "piped; on a tty this exits with code 2)."
        ),
    )
    chatbox_parser.add_argument(
        "--no-send",
        action="store_true",
        help="Place text in the input field without sending.",
    )
    chatbox_parser.add_argument(
        "--no-sfx",
        action="store_true",
        help="Suppress the chatbox notification sound.",
    )

    typing_parser = actions.add_parser(
        "typing",
        help="Set the chatbox typing indicator (on/off).",
    )
    typing_parser.add_argument(
        "state",
        choices=("on", "off"),
        help="Show (on) or hide (off) the typing indicator.",
    )

    avatar_parser = actions.add_parser(
        "avatar",
        help=("Write to /avatar/parameters/<name> (--bool / --int / --float)."),
    )
    avatar_parser.add_argument(
        "name",
        help="Avatar parameter name (no slashes, non-empty).",
    )
    avatar_type = avatar_parser.add_mutually_exclusive_group(required=True)
    avatar_type.add_argument(
        "--bool",
        dest="bool_value",
        choices=_BOOL_CHOICES,
        help=(
            "Send as bool. Accepted values: true / false / 1 / 0. "
            "VRChat receives 0 or 1 as an int tag."
        ),
    )
    avatar_type.add_argument(
        "--int",
        dest="int_value",
        type=int,
        help="Send as int. Must be in [0, 255].",
    )
    avatar_type.add_argument(
        "--float",
        dest="float_value",
        type=float,
        help="Send as float. Must be in [-1.0, 1.0].",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch ``osc <action>``.

    Validation errors from the underlying senders collapse to exit 1.
    ``chatbox`` with no text and a tty stdin exits 2 (same shape as
    :mod:`vrcpilot.cli.paste`).
    """
    try:
        match args.osc_action:
            case "send":
                sender = _make_sender(args.host, args.port)
                if args.bool_value is not None:
                    sender.send_bool(args.address, _parse_bool_str(args.bool_value))
                elif args.int_value is not None:
                    sender.send_int(args.address, args.int_value)
                else:
                    sender.send_float(args.address, args.float_value)
            case "axis":
                getattr(_make_controller(args), _to_method(args.name))(args.value)
            case "tap":
                getattr(_make_controller(args), _to_method(args.name))()
            case "hold":
                getattr(_make_controller(args), _to_method(args.name))(
                    args.state == "on"
                )
            case "chatbox":
                raw: str | None = args.text
                if raw is None:
                    if sys.stdin.isatty():
                        print(
                            "vrcpilot: chatbox text required (positional or stdin)",
                            file=sys.stderr,
                        )
                        return 2
                    text = sys.stdin.read()
                else:
                    text = raw
                _make_controller(args).chatbox(
                    text, send=not args.no_send, sfx=not args.no_sfx
                )
            case "typing":
                _make_controller(args).typing(args.state == "on")
            case "avatar":
                avatar_params = _make_sender(args.host, args.port).avatar_parameters()
                if args.bool_value is not None:
                    avatar_params.send_bool(args.name, _parse_bool_str(args.bool_value))
                elif args.int_value is not None:
                    avatar_params.send_int(args.name, args.int_value)
                else:
                    avatar_params.send_float(args.name, args.float_value)
            case _:  # pragma: no cover - argparse required=True prevents this
                raise AssertionError(f"Unknown osc action: {args.osc_action!r}")
    except ValueError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    return 0
