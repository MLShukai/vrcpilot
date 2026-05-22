"""``vrcpilot mic`` subcommand.

Stream float32 PCM into a virtual mic device (VB-Cable on Windows,
the ``VRCPilotMic`` PipeWire null-sink on Linux). Reads from a WAV
file (``-i path.wav``) or raw ``s16le`` over stdin so upstream tools
such as ``ffmpeg -f s16le ...`` or a Python LLM-TTS pipeline can pipe
audio directly into VRChat's mic.

Exit codes:
    * ``0`` -- playback completed.
    * ``1`` -- recoverable runtime failure: device lookup miss
      (:class:`~vrcpilot.mic.MicDeviceNotFoundError`), unsupported WAV
      (sampwidth != 2), or a soundcard / libpulse / WASAPI failure
      (``ImportError`` / ``OSError`` / ``RuntimeError``).
    * ``2`` -- bad argument combination (no input on a tty, ``auto``
      format against a non-WAV extension).
"""

from __future__ import annotations

import argparse
import sys
import wave
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO, BinaryIO

import numpy as np
from argcomplete.completers import FilesCompleter
from numpy.typing import NDArray

from vrcpilot.mic import Mic, MicDeviceNotFoundError
from vrcpilot.mic.base import LIBPULSE_HINT

from ._common import SubParsersAction, attach_completer

#: ``int16`` -> ``float32`` divisor that keeps ``int16.min`` from
#: saturating past ``-1.0`` (which clips inside soundcard's
#: float -> driver path) while leaving the positive side at near-unity.
_INT16_DIVISOR: float = 32768.0


def register(subparsers: SubParsersAction) -> None:
    """Wire the ``mic`` subparser into the top-level CLI."""
    parser = subparsers.add_parser(
        "mic",
        help=(
            "Stream PCM (WAV file or raw s16le) into a virtual mic device. "
            "Reads stdin by default so upstream tools (ffmpeg -f s16le, a "
            "Python TTS pipeline, ...) can pipe audio into VRChat's mic."
        ),
    )
    input_action = parser.add_argument(
        "-i",
        "--input",
        type=str,
        default="-",
        metavar="PATH",
        help=(
            "Audio source. '-' (default) reads from stdin. A '.wav' path is "
            "decoded with the stdlib wave module; other paths are treated as "
            "raw s16le when --format is explicit."
        ),
    )
    attach_completer(
        input_action, FilesCompleter(allowednames=("wav",), directories=True)
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        metavar="NAME",
        help=(
            "Output-device name substring. When omitted, falls back to "
            "$VRCPILOT_MIC_DEVICE then the OS default (CABLE Input on Windows)."
        ),
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=48000,
        metavar="HZ",
        help="Sample rate for raw s16le input. Ignored for WAV. Default 48000.",
    )
    parser.add_argument(
        "--channels",
        type=int,
        choices=(1, 2),
        default=2,
        help=(
            "Channel count for raw s16le input. Ignored for WAV. " "Default 2 (stereo)."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("auto", "wav", "s16le"),
        default="auto",
        help=(
            "Force input interpretation. 'auto' (default) decodes file paths "
            "ending in '.wav' as WAV and refuses other extensions; stdin under "
            "'auto' is read as raw s16le."
        ),
    )
    parser.add_argument(
        "--chunk-ms",
        type=int,
        default=100,
        metavar="MS",
        help="Chunk size in milliseconds for raw s16le streaming. Default 100.",
    )


def _wav_to_float32(
    reader: wave.Wave_read,
) -> tuple[NDArray[np.float32], int, int]:
    """Decode a WAV into the chunk shape :class:`vrcpilot.mic.Mic` expects.

    Returns ``(samples, framerate, channels)`` where ``samples`` is
    ``(N,)`` for mono input or ``(N, channels)`` otherwise.

    Raises:
        wave.Error: ``sampwidth != 2`` (not 16-bit signed PCM).
    """
    sampwidth = reader.getsampwidth()
    if sampwidth != 2:
        raise wave.Error(
            f"only 16-bit signed PCM WAV is supported, got sampwidth={sampwidth}"
        )
    channels = reader.getnchannels()
    framerate = reader.getframerate()
    raw = reader.readframes(reader.getnframes())
    pcm = np.frombuffer(raw, dtype=np.int16)
    samples = pcm.astype(np.float32) / _INT16_DIVISOR
    if channels > 1:
        samples = samples.reshape(-1, channels)
    return samples, framerate, channels


def _raw_stream_chunks(
    source: IO[bytes],
    *,
    rate: int,
    channels: int,
    chunk_ms: int,
) -> Iterator[NDArray[np.float32]]:
    """Yield float32 chunks from a raw little-endian s16 PCM stream.

    Reads are aligned to ``channels * 2`` byte boundaries so no
    partial frames cross chunk boundaries (which would misalign
    channels). The final short read is still yielded as long as it
    contains at least one whole frame.
    """
    frame_bytes = channels * 2
    frames_per_chunk = max(1, int(rate * chunk_ms / 1000))
    buf_size = frames_per_chunk * frame_bytes
    while True:
        raw = source.read(buf_size)
        if not raw:
            return
        # Trim any trailing partial frame; carrying it forward would
        # misalign channels in subsequent chunks.
        usable = (len(raw) // frame_bytes) * frame_bytes
        if usable == 0:
            return
        pcm = np.frombuffer(raw[:usable], dtype=np.int16)
        samples = pcm.astype(np.float32) / _INT16_DIVISOR
        if channels > 1:
            samples = samples.reshape(-1, channels)
        yield samples


def _is_wav_path(path: Path) -> bool:
    """Whether ``--format auto`` should treat ``path`` as a WAV file."""
    return path.suffix.lower() == ".wav"


def _stdin_buffer() -> BinaryIO:
    """Indirection over ``sys.stdin.buffer`` so tests can patch it."""
    return sys.stdin.buffer


def _resolve_input(
    args: argparse.Namespace,
) -> tuple[Iterable[NDArray[np.float32]], int, int] | int:
    """Resolve CLI args to ``(chunks, channels, sample_rate)`` or an exit code.

    Returns an integer exit code in place of the tuple when the input
    is unresolvable (tty stdin, ``auto`` format against an unknown
    extension). The chunks iterable is a one-element list for WAV
    inputs (decoded eagerly) or a generator for raw s16le.
    """
    input_arg: str = args.input
    fmt: str = args.format

    if input_arg == "-":
        if sys.stdin.isatty():
            print(
                "vrcpilot: no audio piped to stdin; "
                "pass -i <path> or pipe data into stdin",
                file=sys.stderr,
            )
            return 2
        if fmt == "wav":
            with wave.open(_stdin_buffer(), "rb") as reader:
                samples, framerate, channels = _wav_to_float32(reader)
            return [samples], channels, framerate
        # ``auto`` over a stdin pipe is raw s16le: no extension to
        # inspect, and headerless s16le is what upstream producers
        # (ffmpeg ``-f s16le``, TTS pipelines, ...) emit.
        chunks = _raw_stream_chunks(
            _stdin_buffer(),
            rate=args.rate,
            channels=args.channels,
            chunk_ms=args.chunk_ms,
        )
        return chunks, args.channels, args.rate

    path = Path(input_arg)
    use_wav = fmt == "wav" or (fmt == "auto" and _is_wav_path(path))
    if use_wav:
        with wave.open(str(path), "rb") as reader:
            samples, framerate, channels = _wav_to_float32(reader)
        return [samples], channels, framerate
    if fmt == "s16le":
        # The generator closes over the open file handle so it stays
        # alive until Mic finishes consuming it.
        chunks = _raw_stream_chunks(
            path.open("rb"),
            rate=args.rate,
            channels=args.channels,
            chunk_ms=args.chunk_ms,
        )
        return chunks, args.channels, args.rate
    print(
        f"vrcpilot: cannot auto-detect format for {path}; "
        "pass --format wav or --format s16le",
        file=sys.stderr,
    )
    return 2


def run(args: argparse.Namespace) -> int:
    """Execute ``vrcpilot mic``; see module docstring for exit-code
    contract."""
    try:
        resolved = _resolve_input(args)
    except wave.Error as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    if isinstance(resolved, int):
        return resolved
    chunks, channels, play_rate = resolved

    try:
        print(
            f"Playing audio into mic device at {play_rate} Hz " f"({channels} ch).",
            file=sys.stderr,
        )
        with Mic(args.device, sample_rate=play_rate, channels=channels) as mic:
            for chunk in chunks:
                mic.play(chunk)
    except MicDeviceNotFoundError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    except wave.Error as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as exc:
        # ``OSError`` covers file-open failures and soundcard's dlopen
        # failure (libpulse / WASAPI missing). ``RuntimeError`` is
        # soundcard's runtime fault channel (libpulse server errors,
        # WASAPI device I/O failures). Both collapse to exit 1 so the
        # CLI contract holds instead of bubbling a traceback. When
        # libpulse is implicated, mirror the install hint
        # ``vrcpilot linux-mic status`` prints so both CLIs speak in
        # the same voice.
        msg = str(exc)
        print(f"vrcpilot: {msg}", file=sys.stderr)
        if "libpulse" in msg.lower():
            print(f"vrcpilot: hint: {LIBPULSE_HINT}", file=sys.stderr)
        return 1
    return 0
