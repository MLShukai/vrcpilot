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

from vrcpilot.screenshot import take_screenshot

from ._common import SubParsersAction, attach_completer


def register(subparsers: SubParsersAction) -> None:
    """Add the ``screenshot`` subparser to the top-level subparsers."""
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


def run(args: argparse.Namespace) -> int:
    """Run ``screenshot``; exit 1 (empty stdout) when capture fails."""
    output: Path | None = args.output
    shot = take_screenshot()
    if shot is None:
        print("vrcpilot: could not capture VRChat screenshot", file=sys.stderr)
        return 1
    sys.stdout.write(shot.save(output))
    return 0
