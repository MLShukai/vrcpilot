"""``vrcpilot mic`` subcommand.

Stream float32 PCM into a virtual mic device (typically VB-Cable on
Windows). Designed as the symmetric counterpart of
:mod:`vrcpilot.cli.record`: ``record`` writes raw s16le or a WAV file,
and ``mic`` consumes the same payload to play it back into VRChat's
microphone input. The default input is stdin so
``vrcpilot record | vrcpilot mic`` works without intermediate files.

Exit codes:
    * ``0`` -- playback completed successfully.
    * ``1`` -- recoverable runtime failure: device lookup miss
      (:class:`~vrcpilot.mic.MicDeviceNotFoundError`), unsupported WAV
      (sampwidth != 2), PortAudio failure, or sounddevice not installed.
    * ``2`` -- bad argument combination (no input on a tty, ``auto``
      format against a non-WAV extension).
"""

from __future__ import annotations

import argparse
import sys
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import IO, BinaryIO

import numpy as np
from argcomplete.completers import FilesCompleter
from numpy.typing import NDArray

from vrcpilot.mic import Mic, MicDeviceNotFoundError

from ._common import SubParsersAction, attach_completer

#: Divisor used to scale ``int16`` -> ``float32`` for playback.
#:
#: ``np.int16(-32768) / 32768.0`` is exactly ``-1.0`` and
#: ``np.int16(32767) / 32768.0`` is ``~0.999969``: the asymmetric divisor
#: keeps ``int16.min`` from saturating past ``-1.0`` (which would clip
#: inside sounddevice's float -> driver path) while still preserving
#: near-unity on the positive side.
_INT16_DIVISOR: float = 32768.0


def register(subparsers: SubParsersAction) -> None:
    """Add the ``mic`` subparser to the top-level subparsers."""
    parser = subparsers.add_parser(
        "mic",
        help=(
            "Stream PCM (WAV file or raw s16le) into a virtual mic device. "
            "Defaults to reading from stdin so 'vrcpilot record | vrcpilot mic' "
            "round-trips audio back into VRChat."
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
            "Channel count for raw s16le input. Ignored for WAV. Default 2 to "
            "match 'vrcpilot record' (stereo s16le)."
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


def _wav_to_float32(reader: wave.Wave_read) -> tuple[NDArray[np.float32], int]:
    """Decode an open :class:`wave.Wave_read` to a single float32 chunk.

    Returns the ``(samples, framerate)`` pair where ``samples`` is
    shape ``(N,)`` for mono input or ``(N, channels)`` for multi-channel
    input -- matching :meth:`vrcpilot.mic.Mic.play`'s channel inference.

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
    return samples, framerate


def _raw_stream_chunks(
    source: IO[bytes],
    *,
    rate: int,
    channels: int,
    chunk_ms: int,
) -> Iterator[NDArray[np.float32]]:
    """Yield float32 chunks read from ``source`` as little-endian s16 PCM.

    ``chunk_ms`` is rounded down to the nearest whole frame so the
    buffer size stays an exact multiple of ``channels * 2`` bytes and
    no partial frames survive across reads. A short final read (the
    stream's leftover bytes that do not fill a chunk) is still yielded
    as long as it contains at least one whole frame.
    """
    frame_bytes = channels * 2
    frames_per_chunk = max(1, int(rate * chunk_ms / 1000))
    buf_size = frames_per_chunk * frame_bytes
    while True:
        raw = source.read(buf_size)
        if not raw:
            return
        # Trim any trailing partial frame: feeding it to sounddevice
        # would misalign channels in subsequent chunks.
        usable = (len(raw) // frame_bytes) * frame_bytes
        if usable == 0:
            return
        pcm = np.frombuffer(raw[:usable], dtype=np.int16)
        samples = pcm.astype(np.float32) / _INT16_DIVISOR
        if channels > 1:
            samples = samples.reshape(-1, channels)
        yield samples


def _is_wav_path(path: Path) -> bool:
    """Whether ``auto`` should treat ``path`` as a WAV file."""
    return path.suffix.lower() == ".wav"


def _stdin_buffer() -> BinaryIO:
    """Return ``sys.stdin.buffer`` -- isolated so tests can patch it."""
    return sys.stdin.buffer


def run(args: argparse.Namespace) -> int:
    """Execute the ``mic`` subcommand; see module docstring for exits."""
    input_arg: str = args.input
    fmt: str = args.format
    chunk_ms: int = args.chunk_ms
    rate: int = args.rate
    channels: int = args.channels

    # Build the play() argument pair upfront so the Mic boundary stays
    # a single try-block. ``stream`` is either a one-element list (for
    # WAV / single-buffer decodes) or a generator (raw s16le).
    stream: list[NDArray[np.float32]] | Iterator[NDArray[np.float32]]
    play_rate: int

    try:
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
                    samples, framerate = _wav_to_float32(reader)
                stream = [samples]
                play_rate = framerate
            else:
                # 'auto' on stdin pipes is treated as raw s16le -- there
                # is no extension to inspect, and the symmetric
                # 'vrcpilot record' default emits headerless s16le.
                stream = _raw_stream_chunks(
                    _stdin_buffer(),
                    rate=rate,
                    channels=channels,
                    chunk_ms=chunk_ms,
                )
                play_rate = rate
        else:
            path = Path(input_arg)
            use_wav = fmt == "wav" or (fmt == "auto" and _is_wav_path(path))
            if use_wav:
                with wave.open(str(path), "rb") as reader:
                    samples, framerate = _wav_to_float32(reader)
                stream = [samples]
                play_rate = framerate
            elif fmt == "s16le":
                # Generator owns the open file handle so it stays alive
                # until the Mic finishes consuming it.
                stream = _raw_stream_chunks(
                    path.open("rb"),
                    rate=rate,
                    channels=channels,
                    chunk_ms=chunk_ms,
                )
                play_rate = rate
            else:
                # auto + non-.wav: refuse rather than guess.
                print(
                    f"vrcpilot: cannot auto-detect format for {path}; "
                    "pass --format wav or --format s16le",
                    file=sys.stderr,
                )
                return 2

        print(f"Playing audio into mic device at {play_rate} Hz.", file=sys.stderr)
        Mic(args.device).play(stream, sample_rate=play_rate)
    except MicDeviceNotFoundError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    except wave.Error as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        # File-open failures (missing path, permission denied) and any
        # underlying PortAudio I/O surface as OSError subclasses.
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # sounddevice.PortAudioError inherits from Exception (not
        # OSError); funnelling residual hardware faults through here
        # keeps the CLI exit contract (code 1) intact instead of
        # crashing with a traceback.
        if type(exc).__name__ != "PortAudioError":
            raise
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1
    return 0
