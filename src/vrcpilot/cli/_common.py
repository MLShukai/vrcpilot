"""Shared helpers for the :mod:`vrcpilot.cli` subcommand modules."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from argcomplete.completers import FilesCompleter

from vrcpilot.screenshot import Screenshot

# argparse does not export the subparsers-action class publicly but it
# is exactly what ``add_subparsers()`` returns — typing the per-command
# ``register()`` hooks against it keeps the API self-documenting at the
# cost of a single private-usage suppression.
type SubParsersAction = argparse._SubParsersAction[argparse.ArgumentParser]  # pyright: ignore[reportPrivateUsage]


def attach_completer(action: argparse.Action, completer: object) -> None:
    """Attach an ``argcomplete`` completer to ``action``.

    ``argcomplete`` reads ``action.completer`` dynamically; routing via
    ``setattr`` keeps pyright-strict noise off the registration sites.
    """
    setattr(action, "completer", completer)  # noqa: B010 - argcomplete's documented hook


def add_screenshot_input_arg(parser: argparse.ArgumentParser) -> None:
    """Register the shared ``-s/--screenshot <yaml>`` input flag.

    Pair with :func:`resolve_screenshot` so subcommands consume
    screenshots through one contract (file flag or piped stdin).
    """
    action = parser.add_argument(
        "-s",
        "--screenshot",
        type=Path,
        default=None,
        metavar="YAML",
        help=(
            "Read a previously captured screenshot from this YAML file "
            "(as emitted by ``vrcpilot screenshot``) instead of capturing "
            "a fresh one."
        ),
    )
    attach_completer(
        action, FilesCompleter(allowednames=("yaml", "yml"), directories=True)
    )


def resolve_screenshot(args: argparse.Namespace) -> Screenshot | None:
    """Resolve a :class:`Screenshot` from ``--screenshot`` or piped stdin.

    ``--screenshot`` wins over stdin when both are present (the stdin
    payload is silently ignored). Returns ``None`` after writing a
    ``vrcpilot: ...`` stderr line on every failure mode (missing file,
    bad YAML, or no source at all); callers typically map that to
    ``return 1``.
    """
    screenshot_arg: Path | None = getattr(args, "screenshot", None)
    if screenshot_arg is not None:
        try:
            text = screenshot_arg.read_text()
        except FileNotFoundError:
            print(
                f"vrcpilot: --screenshot file not found: {screenshot_arg}",
                file=sys.stderr,
            )
            return None
        try:
            return Screenshot.load(text)
        except ValueError as exc:
            print(f"vrcpilot: {exc}", file=sys.stderr)
            return None

    if not sys.stdin.isatty():
        try:
            return Screenshot.load(sys.stdin.read())
        except ValueError as exc:
            print(f"vrcpilot: {exc}", file=sys.stderr)
            return None

    print(
        "vrcpilot: no screenshot provided; "
        "pass --screenshot <yaml> or pipe 'vrcpilot screenshot' output via stdin",
        file=sys.stderr,
    )
    return None
