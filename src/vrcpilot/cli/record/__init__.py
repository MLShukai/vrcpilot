"""``vrcpilot record`` subcommand: unified video / audio recorder.

Mode is derived from ``--video`` / ``--audio``: both unset (or both
set) means ``"both"``; otherwise the single flag wins. Muxer choice
follows the output: ``.mp4`` (file, with video), ``.wav`` (file,
audio-only), or Matroska over stdout when ``-o`` is omitted —
Matroska is required for pipe mode because MP4 needs to seek back to
patch ``moov`` on close, which a pipe forbids.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from argcomplete.completers import FilesCompleter

from vrcpilot.capture import CaptureLoop
from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.speaker import SpeakerLoop

from .._common import (
    SubParsersAction,
    add_pid_arg,
    attach_completer,
    handle_multi_instance_error,
)
from .muxer import BaseMuxer, MkvStdoutMuxer, Mp4FileMuxer, WavFileMuxer

#: Default playback rate used when ``--fps`` is not given. Mirrors the
#: previous ``capture`` subcommand default so downstream tooling can
#: rely on a stable target frame rate when none is specified.
_DEFAULT_FPS: float = 30.0

type _Mode = Literal["both", "video", "audio"]


def register(subparsers: SubParsersAction) -> None:
    """Wire the ``record`` subparser into the top-level CLI."""
    record_parser = subparsers.add_parser(
        "record",
        help="Record VRChat video and/or audio to a file or stdout pipe.",
    )
    record_output_action = record_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Where to write the recording. With no value, streams a "
            "Matroska (MKV) container to stdout (pipe to ffmpeg etc.). "
            "With an existing directory, writes "
            "<dir>/vrcpilot_record_<YYYYMMDD_HHMMSS>.{mp4,wav} based on "
            "mode. Otherwise, treats the value as an explicit file "
            "path; the extension must be .mp4 for video/both mode or "
            ".wav for audio-only mode."
        ),
    )
    attach_completer(
        record_output_action,
        FilesCompleter(allowednames=("mp4", "wav"), directories=True),
    )
    record_parser.add_argument(
        "--video",
        action="store_true",
        help=(
            "Record video. Combined with --audio (or neither) means "
            "both video and audio are recorded."
        ),
    )
    record_parser.add_argument(
        "--audio",
        action="store_true",
        help=(
            "Record audio. Combined with --video (or neither) means "
            "both video and audio are recorded."
        ),
    )
    record_parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help=(
            "Target frames per second for the video stream (default: "
            "30.0). Must not be combined with audio-only mode."
        ),
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
    add_pid_arg(record_parser)


def _resolve_mode(*, video: bool, audio: bool) -> _Mode:
    """Map ``--video`` / ``--audio`` to a mode; ``"both"`` is the default."""
    if video and not audio:
        return "video"
    if audio and not video:
        return "audio"
    return "both"


def _required_extension(mode: _Mode) -> str:
    """Return the mandatory output extension for ``mode``."""
    return ".wav" if mode == "audio" else ".mp4"


def _default_filename(mode: _Mode, *, now: datetime) -> str:
    """Compose the timestamped default filename used when ``-o`` is a dir."""
    stamp = now.strftime("%Y%m%d_%H%M%S")
    return f"vrcpilot_record_{stamp}{_required_extension(mode)}"


def _resolve_output(arg: Path | None, *, mode: _Mode, now: datetime) -> Path | None:
    """Resolve ``args.output``; ``None`` signals stdout pipe mode.

    A directory argument expands to the mode-aware default filename;
    ``now`` is injected so tests pin the timestamp deterministically.
    """
    if arg is None:
        return None
    if arg.is_dir():
        return arg / _default_filename(mode, now=now)
    return arg


def _extension_error_message(mode: _Mode, path: Path) -> str:
    """Format the exit-2 stderr line for an output/mode mismatch."""
    if mode == "video":
        return f"vrcpilot: --video requires .mp4 output (got: '{path}')"
    if mode == "audio":
        return f"vrcpilot: --audio requires .wav output (got: '{path}')"
    return f"vrcpilot: video+audio output requires .mp4 (got: '{path}')"


def _validate_extension(target: Path, mode: _Mode) -> bool:
    """Return ``True`` when ``target``'s suffix matches ``mode``."""
    return target.suffix == _required_extension(mode)


def _build_file_muxer(target: Path, mode: _Mode, fps: float) -> BaseMuxer:
    """Pick a concrete file-backed muxer for ``mode``."""
    if mode == "audio":
        return WavFileMuxer(target)
    want_video = mode in ("both", "video")
    want_audio = mode in ("both", "audio")
    return Mp4FileMuxer(target, fps=fps, video=want_video, audio=want_audio)


def _build_stdout_muxer(mode: _Mode, fps: float) -> BaseMuxer:
    """Build the Matroska-over-stdout muxer for ``mode``."""
    want_video = mode in ("both", "video")
    want_audio = mode in ("both", "audio")
    return MkvStdoutMuxer(fps=fps, video=want_video, audio=want_audio)


def run(args: argparse.Namespace) -> int:
    """Record VRChat video and/or audio to a file or stdout pipe.

    File mode prints the saved absolute path to stdout; pipe mode
    writes the raw MKV byte stream there. Progress chatter always
    goes to stderr so stdout stays parseable in file mode and
    byte-clean in pipe mode.

    Exit codes:

    * 0: recording completed and at least one frame or sample reached
      the muxer
    * 1: runtime failure (VRChat down, no data captured, refused to
      stream MKV to a TTY)
    * 2: argument-shape mismatch (output extension does not match
      mode, or ``--fps`` combined with audio-only)
    """
    mode = _resolve_mode(video=args.video, audio=args.audio)
    fps_arg: float | None = args.fps
    if mode == "audio" and fps_arg is not None:
        print(
            "vrcpilot: --fps is not meaningful with --audio "
            "(drop --fps or remove --audio)",
            file=sys.stderr,
        )
        return 2
    fps: float = fps_arg if fps_arg is not None else _DEFAULT_FPS

    target = _resolve_output(args.output, mode=mode, now=datetime.now())
    if target is not None and not _validate_extension(target, mode):
        print(_extension_error_message(mode, target), file=sys.stderr)
        return 2

    duration: float | None = args.duration
    pid: int | None = args.pid

    if target is None:
        if sys.stdout.isatty():
            print(
                "vrcpilot: refusing to write a MKV stream to a TTY; "
                "pipe stdout or pass -o <path>",
                file=sys.stderr,
            )
            return 1
        muxer = _build_stdout_muxer(mode, fps)
        progress_target = "stdout (MKV)"
    else:
        muxer = _build_file_muxer(target, mode, fps)
        progress_target = str(target)

    try:
        with contextlib.ExitStack() as stack:
            stack.enter_context(muxer)

            capture_loop: CaptureLoop | None = None
            speaker_loop: SpeakerLoop | None = None
            if mode in ("both", "video"):
                capture_loop = stack.enter_context(
                    CaptureLoop(muxer.write_video, fps=fps, pid=pid)
                )
            if mode in ("both", "audio"):
                speaker_loop = stack.enter_context(
                    SpeakerLoop(muxer.write_audio, pid=pid)
                )

            if capture_loop is not None:
                capture_loop.start()
            if speaker_loop is not None:
                speaker_loop.start()

            # Progress messages go to stderr so stdout stays parseable
            # (single absolute-path line in file mode) and pipe-clean
            # (MKV bytes only in stdout mode).
            print(
                f"Recording to {progress_target}. Press Ctrl+C to stop.",
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

            saved_frames = muxer.frame_count
            saved_samples = muxer.sample_count
    except VRChatMultipleInstancesError as exc:
        # Subclass of RuntimeError, but we want the canonical multi-
        # instance diagnostic, so handle it before the generic branch.
        handle_multi_instance_error(exc)
        return 1
    except RuntimeError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1

    if saved_frames == 0 and saved_samples == 0:
        print(
            "vrcpilot: no frames or audio samples were recorded",
            file=sys.stderr,
        )
        return 1
    if target is not None:
        print(str(target.resolve()))
    return 0
