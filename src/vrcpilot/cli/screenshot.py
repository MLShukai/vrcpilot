"""``vrcpilot screenshot`` subcommand: capture VRChat to YAML on stdout.

With ``-o`` the PNG is written to disk and YAML carries a ``path``
reference; without ``-o`` the PNG is base64-embedded under ``image:``
so ``vrcpilot screenshot | vrcpilot ocr`` works without stray files.
See ``docs/cli.md`` for the full schema.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from argcomplete.completers import FilesCompleter

from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.screenshot import take_screenshot

from ._common import (
    SubParsersAction,
    add_pid_arg,
    attach_completer,
    handle_multi_instance_error,
)


def register(subparsers: SubParsersAction) -> None:
    """Wire the ``screenshot`` subparser into the top-level CLI."""
    screenshot_parser = subparsers.add_parser(
        "screenshot",
        help="Capture a screenshot of the running VRChat window.",
    )
    output_action = screenshot_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Path where the PNG screenshot is written. When omitted, the "
            "image is embedded as base64 PNG in the YAML output (no file "
            "is written) so the result can be piped directly to "
            "'vrcpilot ocr' / 'detect'."
        ),
    )
    attach_completer(
        output_action, FilesCompleter(allowednames=("png",), directories=True)
    )
    add_pid_arg(screenshot_parser)


def run(args: argparse.Namespace) -> int:
    """Capture the VRChat window and emit YAML on stdout.

    Exit 1 with ``vrcpilot: ...`` on stderr (empty stdout) when
    :func:`vrcpilot.screenshot.take_screenshot` cannot produce a frame
    or the multi-instance guard fires without ``--pid``.
    """
    output: Path | None = args.output
    try:
        shot = take_screenshot(pid=args.pid)
    except VRChatMultipleInstancesError as exc:
        handle_multi_instance_error(exc)
        return 1
    if shot is None:
        print("vrcpilot: could not capture VRChat screenshot", file=sys.stderr)
        return 1
    sys.stdout.write(shot.save(output))
    return 0
