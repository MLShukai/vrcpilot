"""Shared helpers reused across the :mod:`vrcpilot.cli` subcommand modules.

Centralises the per-subcommand argparse fragments (``--pid`` flag,
``--screenshot`` input flag) and the canonical stderr diagnostic for
the multi-instance VRChat case so every subcommand surfaces the same
guidance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml
from argcomplete.completers import FilesCompleter

from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.screenshot import Screenshot

# argparse does not publish the subparsers-action class but ``add_subparsers``
# returns exactly this; the explicit alias keeps the ``register(...)`` hooks
# self-documenting at the cost of one private-usage suppression.
type SubParsersAction = argparse._SubParsersAction[argparse.ArgumentParser]  # pyright: ignore[reportPrivateUsage]


def add_pid_arg(parser: argparse.ArgumentParser) -> None:
    """Register the shared ``--pid`` flag on a PID-dependent subcommand.

    Every PID-dependent subcommand follows one contract: pass
    ``--pid <int>`` to target a specific VRChat instance, or omit it
    and let :func:`vrcpilot.process.resolve_pid` pick the sole running
    instance. When two or more VRChat processes are alive without
    ``--pid``, the API raises :class:`VRChatMultipleInstancesError` and
    each subcommand routes it through
    :func:`handle_multi_instance_error` for a uniform exit-1 diagnostic.
    """
    parser.add_argument(
        "--pid",
        type=int,
        default=None,
        metavar="PID",
        help=(
            "Target a specific VRChat PID. When omitted, vrcpilot picks "
            "the single running instance automatically; if multiple "
            "VRChat processes are running, the command exits 1 with a "
            "diagnostic listing the candidate PIDs."
        ),
    )


def handle_multi_instance_error(exc: VRChatMultipleInstancesError) -> None:
    """Print the canonical multi-instance diagnostic to stderr.

    Shared across PID-dependent subcommands so a forgotten ``--pid`` on
    a multi-instance host always surfaces as the same line:
    ``vrcpilot: multiple VRChat instances detected (PIDs: <p1> <p2> ...);
    pass --pid``. Callers follow this with ``return 1``.
    """
    pids_str = " ".join(str(p) for p in exc.pids)
    print(
        f"vrcpilot: multiple VRChat instances detected (PIDs: {pids_str}); pass --pid",
        file=sys.stderr,
    )


def attach_completer(action: argparse.Action, completer: object) -> None:
    """Bind an ``argcomplete`` completer to a parsed argparse action.

    ``argcomplete`` reads ``action.completer`` dynamically; routing
    through ``setattr`` keeps pyright-strict noise off the registration
    sites.
    """
    setattr(action, "completer", completer)  # noqa: B010 - argcomplete's documented hook


def add_screenshot_input_arg(parser: argparse.ArgumentParser) -> None:
    """Register the shared ``-s/--screenshot <yaml>`` input flag.

    Pair with :func:`resolve_screenshot` so every screenshot-consuming
    subcommand accepts the same two inputs (file flag or piped stdin)
    with identical precedence.
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

    ``--screenshot`` wins over stdin when both are present; the stdin
    payload is then silently discarded. On every failure mode (missing
    file, bad YAML, or no source at all) the function writes a single
    ``vrcpilot: ...`` line to stderr and returns ``None``; callers
    typically map that to ``return 1``.
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


def emit_yaml(payload: Any) -> None:
    """Dump ``payload`` as YAML to stdout, preserving non-ASCII characters.

    ``yaml.safe_dump(..., allow_unicode=True)`` returns a ``str``; writing
    that via ``sys.stdout.write`` re-encodes through the terminal's
    codepage (cp932 on Japanese-locale Windows), so consumers downstream
    of a pipe or file redirect end up with cp932 bytes instead of the
    UTF-8 they expect. Write the encoded bytes through ``sys.stdout.buffer``
    when available; fall back to ``write`` for pytest ``capsys`` which
    replaces ``sys.stdout`` with a buffer-less stand-in.
    """
    text = yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
    else:
        buffer.write(text.encode("utf-8"))
