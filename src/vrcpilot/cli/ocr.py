"""``vrcpilot ocr`` subcommand: OCR over a screenshot.

Word coordinates are window-local so they feed straight into
``vrcpilot mouse move``. Screenshot input comes from ``--screenshot``
or piped stdin; OCR never captures a fresh shot itself. See
``docs/cli.md`` for the YAML schema.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml
from argcomplete.completers import FilesCompleter
from PIL import Image

from vrcpilot.ocr.recognize import ocr
from vrcpilot.ocr.visualize import render

from ._common import (
    SubParsersAction,
    add_screenshot_input_arg,
    attach_completer,
    resolve_screenshot,
)

# Sentinel that distinguishes "--viz absent" (``None``) from
# "--viz with no argument" (this object) once argparse has parsed the
# argv. ``type=Path`` is only applied when the user passes a value, so
# ``args.viz`` ends up as one of: ``None`` / ``_VIZ_DEFAULT`` / ``Path``.
_VIZ_DEFAULT: object = object()


def register(subparsers: SubParsersAction) -> None:
    """Wire the ``ocr`` subparser into the top-level CLI."""
    parser = subparsers.add_parser(
        "ocr",
        help="Run OCR on the running VRChat window.",
    )
    viz_action = parser.add_argument(
        "--viz",
        nargs="?",
        const=_VIZ_DEFAULT,
        default=None,
        type=Path,
        help=(
            "Save OCR visualization PNG. With no path, writes to cwd "
            "with a timestamp; with a directory, writes inside that "
            "directory using the same default filename."
        ),
    )
    attach_completer(
        viz_action, FilesCompleter(allowednames=("png",), directories=True)
    )
    add_screenshot_input_arg(parser)


def _resolve_viz_path(arg: object, *, now: datetime) -> Path | None:
    """Resolve ``args.viz`` to an output path; ``None`` propagates.

    ``now`` is injected so tests pin the default filename's timestamp
    deterministically instead of racing the wall clock.
    """
    if arg is None:
        return None
    stamp = now.strftime("%Y%m%d_%H%M%S")
    default_name = f"vrcpilot_ocr_viz_{stamp}.png"
    if arg is _VIZ_DEFAULT:
        return Path.cwd() / default_name
    if isinstance(arg, Path):
        if arg.is_dir():
            return arg / default_name
        return arg
    # Defensive fallback: argparse should never hand us anything else,
    # but keeping the branch keeps the type narrowing exhaustive.
    raise TypeError(f"unexpected --viz value: {arg!r}")


def run(args: argparse.Namespace) -> int:
    """OCR the resolved screenshot and emit a YAML payload on stdout.

    Word coordinates in the payload are VRChat window-local so they
    feed straight into ``vrcpilot mouse move``. Exit 1 with
    ``vrcpilot: ...`` on stderr when the screenshot input cannot be
    resolved (no ``--screenshot`` and no piped stdin, missing file,
    or malformed YAML).
    """
    shot = resolve_screenshot(args)
    if shot is None:
        return 1
    result = ocr(shot)

    viz_path = _resolve_viz_path(args.viz, now=datetime.now())
    if viz_path is not None:
        rendered = render(result)
        Image.fromarray(rendered).save(viz_path)

    shot = result.screenshot
    words_payload: list[dict[str, object]] = []
    for word in result.words:
        polygon = [list(point) for point in word.polygon]
        bbox = list(word.bbox)
        words_payload.append(
            {
                "text": word.text,
                "confidence": word.confidence,
                "pos": {
                    "polygon": polygon,
                    "bbox": bbox,
                },
            }
        )

    payload: dict[str, object] = {
        "captured_at": shot.captured_at.isoformat(),
        "window": {
            "x": shot.x,
            "y": shot.y,
            "width": shot.width,
            "height": shot.height,
            "monitor_index": shot.monitor_index,
        },
        "words": words_payload,
    }
    if viz_path is not None:
        payload["viz_path"] = str(viz_path.resolve())

    sys.stdout.write(yaml.safe_dump(payload, sort_keys=False, default_flow_style=False))
    return 0
