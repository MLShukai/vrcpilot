"""``vrcpilot record`` subcommand."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from argcomplete.completers import FilesCompleter

from vrcpilot.speaker import RawPcmStdoutSink, SpeakerLoop, WavFileSink

from ._common import SubParsersAction, attach_completer


def register(subparsers: SubParsersAction) -> None:
    """Add the ``record`` subparser to the top-level subparsers."""
    record_parser = subparsers.add_parser(
        "record",
        help="Record VRChat audio and save as WAV (or pipe raw s16le).",
    )
    record_output_action = record_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Where to write the recording. With no value, streams raw "
            "s16le PCM (48 kHz, stereo, headerless) to stdout (pipe to "
            "ffmpeg etc.). With an existing directory, writes WAV to "
            "<dir>/vrcpilot_record_<YYYYMMDD_HHMMSS>.wav. Otherwise, "
            "treats the value as the WAV file path."
        ),
    )
    attach_completer(
        record_output_action,
        FilesCompleter(allowednames=("wav",), directories=True),
    )
    record_parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help=(
            "Stop after this many seconds. When unset, recording "
            "continues until Ctrl+C."
        ),
    )


def _resolve_output(arg: Path | None, *, now: datetime) -> Path | None:
    """Resolve ``args.output`` to a concrete WAV path or ``None``.

    Args:
        arg: Raw value from ``args.output``. ``None`` (flag absent) means
            the caller wants the stdout raw-PCM pipe. A :class:`Path`
            that points at an existing directory is expanded to a
            timestamped default file inside it. Any other :class:`Path`
            is treated as the explicit WAV path the caller requested.
        now: Timestamp used to build the default filename. Taken as a
            parameter so tests can pin it.

    Returns:
        ``None`` to signal stdout pipe mode, otherwise the resolved
        WAV :class:`Path`.
    """
    if arg is None:
        return None
    stamp = now.strftime("%Y%m%d_%H%M%S")
    default_name = f"vrcpilot_record_{stamp}.wav"
    if arg.is_dir():
        return arg / default_name
    return arg


def run(args: argparse.Namespace) -> int:
    """Execute the ``record`` subcommand.

    Args:
        args: Parsed argparse namespace. Reads ``args.output`` /
            ``args.duration``. ``output`` ``None`` streams raw s16le
            PCM to stdout (refused when stdout is a TTY); a
            :class:`Path` pointing at an existing directory writes
            ``<dir>/vrcpilot_record_<YYYYMMDD_HHMMSS>.wav``; any other
            :class:`Path` is used as the WAV path verbatim. ``duration``
            stops after this many seconds - ``None`` waits for
            ``Ctrl+C`` (KeyboardInterrupt).

    Returns:
        ``0`` on success. In file mode the absolute path of the saved
        WAV (a single line) is written to stdout; in pipe mode stdout
        carries the binary s16le stream and Python writes nothing extra
        there. ``1`` if recording failed, no samples were captured, or
        stdout was a TTY in pipe mode. Progress messages go to stderr
        so stdout stays parseable / pipe-clean.
    """
    target = _resolve_output(args.output, now=datetime.now())
    duration: float | None = args.duration

    sink_cm: WavFileSink | RawPcmStdoutSink
    if target is None:
        if sys.stdout.isatty():
            print(
                "vrcpilot: refusing to write a raw PCM stream to a TTY; "
                "pipe stdout or pass -o <path>",
                file=sys.stderr,
            )
            return 1
        sink_cm = RawPcmStdoutSink()
        progress_target = "stdout (raw s16le 48000 Hz stereo)"
    else:
        sink_cm = WavFileSink(target)
        progress_target = str(target)

    try:
        with sink_cm as sink:
            with SpeakerLoop(sink.write) as loop:
                loop.start()
                # Progress messages go to stderr so stdout stays
                # parseable as a single absolute-path line in file
                # mode, and pipe-clean (binary s16le only) in stdout
                # mode.
                print(
                    f"Recording audio to {progress_target}. Press Ctrl+C to stop.",
                    file=sys.stderr,
                )
                try:
                    if duration is not None:
                        time.sleep(duration)
                    else:
                        while True:
                            time.sleep(3600)
                except KeyboardInterrupt:
                    pass
            saved_samples = sink.sample_count
    except RuntimeError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1

    if saved_samples == 0:
        print("vrcpilot: no audio samples recorded.", file=sys.stderr)
        return 1
    if target is not None:
        print(str(target.resolve()))
    return 0
