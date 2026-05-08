"""``vrcpilot osc`` subcommand.

Thin CLI wrapper over :mod:`vrcpilot.osc`. The full subcommand exposes
seven actions that map onto the public OSC surface:

- ``send`` - raw typed send (``OscSender.send_bool/send_int/send_float``)
- ``axis`` - :class:`InputController` axis inputs (-1.0..1.0)
- ``tap`` - :class:`InputController` tap buttons (1 -> sleep -> 0)
- ``hold`` - :class:`InputController` hold buttons (on/off)
- ``chatbox`` - chatbox text + typing indicator
- ``typing`` - chatbox typing indicator only
- ``avatar`` - :class:`AvatarParameters` send_bool/send_int/send_float

All seven actions are wired in this module: ``send`` plus the three
:class:`InputController` button/axis wrappers (``axis`` / ``tap`` /
``hold``) plus ``chatbox`` / ``typing`` plus the
:class:`AvatarParameters` wrapper (``avatar``).

The :func:`_make_sender` factory below is the stable patch target for
tests (mirrors how ``mouse_api`` works in :mod:`vrcpilot.cli.mouse`).
Tests construct a real :class:`OscSender` with an injected
:class:`tests.fakes.FakeUDPClient` and patch this factory to return it.

The :data:`_AXIS_NAMES` / :data:`_TAP_NAMES` / :data:`_HOLD_NAMES`
tuples are the single source of truth for the kebab-case name choices
exposed to argparse. Each entry maps to an :class:`InputController`
method via :func:`_to_method` (``-`` -> ``_``); the
``TestOscChoiceCoverage`` test asserts every entry resolves to a
callable on a real controller.
"""

from __future__ import annotations

import argparse
import sys
from typing import Final

from vrcpilot.osc import OscSender
from vrcpilot.osc.controller import InputController

from ._common import SubParsersAction

#: Axis-style ``/input/*`` inputs (float in ``[-1.0, 1.0]``).
_AXIS_NAMES: Final[tuple[str, ...]] = (
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
_TAP_NAMES: Final[tuple[str, ...]] = (
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
_HOLD_NAMES: Final[tuple[str, ...]] = (
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
    """Convert a CLI kebab-case name to its :class:`InputController` method.

    The mapping is a straight ``-`` -> ``_`` replacement; no other
    transformations are applied. Caller is responsible for ensuring
    ``name`` is one of the registered choices (argparse enforces this
    via ``choices=``).
    """
    return name.replace("-", "_")


def _parse_bool_str(value: str) -> bool:
    """Convert one of :data:`_BOOL_CHOICES` to a Python ``bool``.

    Used by the shared ``--bool`` flag on ``send`` and ``avatar``.
    Argparse's ``choices=`` already constrains the input to the four
    accepted strings, so this helper is total over its domain.
    """
    return value in ("true", "1")


def _make_sender(host: str, port: int) -> OscSender:
    """Construct an :class:`OscSender` for ``run()`` to use.

    Stable patch target. Tests bind an :class:`OscSender` with a
    :class:`tests.fakes.FakeUDPClient` injected via ``client=`` and
    patch this function to return that pre-built sender, so the real
    :class:`OscSender` validation / dispatch logic runs end-to-end
    while UDP construction is bypassed.
    """
    return OscSender(host=host, port=port)


def _make_controller(args: argparse.Namespace) -> InputController:
    """Build an :class:`InputController` from the shared osc-level flags.

    All five ``InputController``-backed actions (axis / tap / hold /
    chatbox / typing) want the same construction: take ``--host`` /
    ``--port`` / ``--button-hold`` off the parent parser, build a sender
    via :func:`_make_sender` (the test patch target), and ask it for a
    fresh controller view. Centralising this keeps the dispatch in
    :func:`run` to one line per action.
    """
    return _make_sender(args.host, args.port).controller(button_hold=args.button_hold)


def register(subparsers: SubParsersAction) -> None:
    """Add the ``osc`` subparser plus its action sub-subcommands."""
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
        choices=_AXIS_NAMES,
        help="Axis name (kebab-case). One of: " + ", ".join(_AXIS_NAMES) + ".",
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
        choices=_TAP_NAMES,
        help="Tap-button name (kebab-case). One of: " + ", ".join(_TAP_NAMES) + ".",
    )

    hold_parser = actions.add_parser(
        "hold",
        help="Press (on) or release (off) an InputController hold button.",
    )
    hold_parser.add_argument(
        "name",
        choices=_HOLD_NAMES,
        help="Hold-button name (kebab-case). One of: " + ", ".join(_HOLD_NAMES) + ".",
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
    """Execute the ``osc`` subcommand.

    Silent on success. Validation failures (``OscSender`` int / float
    range checks, :class:`AvatarParameters` name validation, chatbox
    length cap) print a single ``vrcpilot: <message>`` line to stderr
    and return exit 1. ``chatbox`` with no text on a tty returns exit
    2 (mirrors :mod:`vrcpilot.cli.paste`).

    Returns:
        ``0`` on success, ``1`` on validation failure, ``2`` if
        ``chatbox`` is invoked without text and stdin is a tty.
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
