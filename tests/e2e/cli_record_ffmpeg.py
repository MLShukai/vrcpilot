"""E2E scenario: ``vrcpilot record --audio`` in both WAV-file and MKV-pipe modes.

Validates the two audio output paths of the unified ``vrcpilot
record`` CLI:

* **Step A** - ``vrcpilot record --audio --duration <N> -o <path.wav>``
  writes a self-contained 16-bit PCM WAV file. Stdout is expected to
  be exactly the absolute path of the saved file, on a single line;
  the WAV itself is inspected via :mod:`wave` for the documented
  contract (48 kHz / stereo / 16-bit) and its RMS level is logged so
  a human can sanity-check the signal.
* **Step B** - ``vrcpilot record --audio --duration <N>`` with no
  ``-o`` writes a Matroska (MKV) byte stream to stdout. Because MKV
  is self-describing we can pipe it into
  ``ffmpeg -i - -c:a pcm_s16le <out.wav>`` with no codec/rate flags
  on the ffmpeg side and round-trip back to a pcm_s16le WAV. The
  resulting file is then validated the same way as Step A.

Run with::

    just e2e-test cli_record_ffmpeg

VRChat is launched in Desktop mode (``no_vr=True``) to match the other
audio-related scenarios and so this works on machines without an HMD.
Both step artifacts land in
``_e2e_artifacts/cli_record_ffmpeg/<YYYYMMDD_HHMMSS>/cli_record_<step>.wav``.

The Step B pipeline uses the standard "tee a Popen pipe" idiom: open
``ffmpeg`` first with ``stdin=PIPE``, hand its write-end to the
``vrcpilot record`` Popen as its ``stdout``, then close our own
reference to ``ffmpeg.stdin`` so ``vrcpilot`` becomes the sole writer.
When the recording duration elapses ``vrcpilot`` exits, the pipe sees
EOF, and ``ffmpeg`` flushes and exits cleanly.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np

import vrcpilot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

#: Wall-clock duration of each recording. Short enough to keep the e2e
#: scenario brisk; long enough that ffprobe can resolve a non-trivial
#: container duration.
_DURATION_SECONDS: float = 5.0

#: Tolerance around ``_DURATION_SECONDS`` when checking the encoded
#: WAV's container duration. Wide enough to absorb worker-thread
#: warm-up jitter and the final partial-frame flush, narrow enough to
#: catch a "ffmpeg never received a sample" regression.
_DURATION_TOLERANCE_SECONDS: float = 1.5

#: Expected sample rate of the recording, matching the proc-tap
#: contract documented on :data:`vrcpilot.speaker.base.SAMPLE_RATE`.
_EXPECTED_SAMPLE_RATE: int = 48000

#: Expected channel count of the recording, matching
#: :data:`vrcpilot.speaker.base.CHANNELS`.
_EXPECTED_CHANNELS: int = 2

#: Expected sample width in bytes for the WAV output. The ``record``
#: CLI writes 16-bit signed PCM, i.e. 2 bytes per sample per channel.
_EXPECTED_SAMPWIDTH: int = 2


def _ffprobe_format(path: Path) -> dict[str, Any]:
    """Return ``ffprobe -show_format -show_streams`` JSON for *path*."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    _helpers.log(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    parsed: Any = json.loads(result.stdout)
    assert isinstance(parsed, dict), f"ffprobe output not a JSON object: {parsed!r}"
    parsed_dict: dict[Any, Any] = parsed  # pyright: ignore[reportUnknownVariableType]
    return parsed_dict


def _rms_dbfs(path: Path) -> float:
    """Return the RMS level of *path* in dBFS, or ``-inf`` for pure silence.

    Mirrors the helper in :mod:`tests.e2e.speaker`: the WAV is 16-bit
    signed PCM, so we read the entire file, combine all channels into
    a single scalar level, and return ``20*log10(rms / 32768)``. A
    perfectly silent file maps to ``-inf`` rather than producing a
    math-domain error.
    """
    with wave.open(str(path), "rb") as reader:
        n_frames = reader.getnframes()
        raw = reader.readframes(n_frames)

    if n_frames == 0:
        return float("-inf")

    samples = np.frombuffer(raw, dtype=np.int16)
    if samples.size == 0:
        return float("-inf")

    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    if rms <= 0.0:
        return float("-inf")
    # Full-scale int16 is 32768 in magnitude (``[-32768, 32767]``).
    return 20.0 * math.log10(rms / 32768.0)


def _assert_wav_contract(path: Path, *, label: str) -> int:
    """Verify *path* is a 48 kHz / stereo / 16-bit WAV with samples.

    Args:
        path: WAV file to inspect.
        label: Step label used in assertion messages so a failure
            points at the right step.

    Returns:
        ``n_frames`` from ``wave.open`` for the caller to log alongside
        other observations.
    """
    assert path.exists(), f"[{label}] expected WAV not written: {path}"
    size = path.stat().st_size
    assert size > 0, f"[{label}] WAV file is empty: {path}"

    with wave.open(str(path), "rb") as reader:
        n_frames = reader.getnframes()
        framerate = reader.getframerate()
        nchannels = reader.getnchannels()
        sampwidth = reader.getsampwidth()

    assert n_frames > 0, f"[{label}] WAV has no frames: {path}"
    assert framerate == _EXPECTED_SAMPLE_RATE, (
        f"[{label}] framerate: expected {_EXPECTED_SAMPLE_RATE}, " f"got {framerate}"
    )
    assert (
        nchannels == _EXPECTED_CHANNELS
    ), f"[{label}] channels: expected {_EXPECTED_CHANNELS}, got {nchannels}"
    assert sampwidth == _EXPECTED_SAMPWIDTH, (
        f"[{label}] sample width (bytes): expected {_EXPECTED_SAMPWIDTH}, "
        f"got {sampwidth}"
    )
    return n_frames


def _step_a_wav_file() -> None:
    """Drive ``vrcpilot record --audio -o <wav>`` and validate the saved
    file."""
    out_path = _helpers.scenario_dir("cli_record_ffmpeg") / "cli_record_wav.wav"

    cmd = [
        "uv",
        "run",
        "vrcpilot",
        "record",
        "--audio",
        "--duration",
        f"{_DURATION_SECONDS}",
        "-o",
        str(out_path),
    ]
    _helpers.log(f"[Step A] $ {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.stderr.strip():
        _helpers.log(f"[Step A]   vrcpilot stderr: {result.stderr.strip()}")
    assert result.returncode == 0, (
        f"[Step A] vrcpilot record exit code: expected 0, got " f"{result.returncode}"
    )

    stdout_line = result.stdout.strip()
    expected_line = str(out_path.resolve())
    assert stdout_line == expected_line, (
        f"[Step A] stdout: expected exactly {expected_line!r}, " f"got {stdout_line!r}"
    )

    n_frames = _assert_wav_contract(out_path, label="Step A")
    duration_seconds = n_frames / _EXPECTED_SAMPLE_RATE
    delta = abs(duration_seconds - _DURATION_SECONDS)
    _helpers.log(
        f"[Step A] saved wav: {out_path} "
        f"(frames={n_frames} duration={duration_seconds:.2f}s "
        f"target={_DURATION_SECONDS:.2f}s delta={delta:.2f}s)"
    )
    assert delta <= _DURATION_TOLERANCE_SECONDS, (
        f"[Step A] WAV duration {duration_seconds:.2f}s outside "
        f"tolerance +/-{_DURATION_TOLERANCE_SECONDS:.2f}s of target "
        f"{_DURATION_SECONDS:.2f}s"
    )

    rms_db = _rms_dbfs(out_path)
    if math.isinf(rms_db):
        _helpers.log("[Step A] RMS = -inf dBFS (file is pure silence)")
    else:
        _helpers.log(f"[Step A] RMS = {rms_db:.2f} dBFS")


def _step_b_stdout_ffmpeg() -> None:
    """Drive ``vrcpilot record --audio | ffmpeg -i - -c:a pcm_s16le <wav>``.

    The MKV stream emitted by ``vrcpilot record --audio`` carries an
    AAC audio stream (see :class:`vrcpilot.cli.record.muxer.MkvStdoutMuxer`).
    ffmpeg re-encodes that AAC payload back to pcm_s16le so the rest
    of the assertions can reuse the WAV-file contract checks from
    Step A.
    """
    out_path = _helpers.scenario_dir("cli_record_ffmpeg") / "cli_record_pipe.wav"

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "-",
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    vrcpilot_cmd = [
        "uv",
        "run",
        "vrcpilot",
        "record",
        "--audio",
        "--duration",
        f"{_DURATION_SECONDS}",
    ]
    _helpers.log(f"[Step B] $ {' '.join(vrcpilot_cmd)} | {' '.join(ffmpeg_cmd)}")

    ffmpeg = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert ffmpeg.stdin is not None  # for type narrowing

    vrc = subprocess.Popen(
        vrcpilot_cmd,
        stdout=ffmpeg.stdin,
        stderr=subprocess.PIPE,
    )

    # Hand sole ownership of the write-end to vrcpilot. Without this
    # close(), ffmpeg's stdin would never see EOF after vrcpilot exits.
    ffmpeg.stdin.close()

    vrc_stderr = vrc.stderr.read() if vrc.stderr is not None else b""
    vrc_rc = vrc.wait()
    ffmpeg_stderr = ffmpeg.stderr.read() if ffmpeg.stderr is not None else b""
    ffmpeg_rc = ffmpeg.wait()

    if vrc_stderr:
        _helpers.log(
            f"[Step B]   vrcpilot stderr: "
            f"{vrc_stderr.decode(errors='replace').strip()}"
        )
    if ffmpeg_stderr:
        _helpers.log(
            f"[Step B]   ffmpeg stderr: "
            f"{ffmpeg_stderr.decode(errors='replace').strip()}"
        )

    assert vrc_rc == 0, f"[Step B] vrcpilot record exit code: expected 0, got {vrc_rc}"
    assert ffmpeg_rc == 0, f"[Step B] ffmpeg exit code: expected 0, got {ffmpeg_rc}"

    n_frames = _assert_wav_contract(out_path, label="Step B")
    _helpers.log(
        f"[Step B] saved wav: {out_path} ({out_path.stat().st_size} bytes, "
        f"frames={n_frames})"
    )

    info = _ffprobe_format(out_path)
    streams_raw: Any = info.get("streams", [])
    assert isinstance(
        streams_raw, list
    ), f"[Step B] ffprobe streams not a list: {streams_raw!r}"
    streams_list: list[Any] = streams_raw  # pyright: ignore[reportUnknownVariableType]
    assert (
        len(streams_list) == 1
    ), f"[Step B] expected exactly 1 stream, got {len(streams_list)}: {streams_list!r}"
    audio_streams = [
        s
        for s in streams_list
        if isinstance(s, dict) and s.get("codec_type") == "audio"
    ]
    assert (
        len(audio_streams) == 1
    ), f"[Step B] expected 1 audio stream, got {len(audio_streams)}: {streams_list!r}"
    audio: dict[Any, Any] = audio_streams[0]  # pyright: ignore[reportUnknownVariableType]
    codec: Any = audio.get("codec_name")
    assert codec == "pcm_s16le", f"[Step B] expected pcm_s16le codec, got {codec!r}"
    sample_rate_str: Any = audio.get("sample_rate")
    assert isinstance(
        sample_rate_str, str
    ), f"[Step B] missing sample_rate in ffprobe audio stream: {audio!r}"
    assert int(sample_rate_str) == _EXPECTED_SAMPLE_RATE, (
        f"[Step B] sample_rate: expected {_EXPECTED_SAMPLE_RATE}, "
        f"got {sample_rate_str}"
    )
    channels: Any = audio.get("channels")
    assert (
        channels == _EXPECTED_CHANNELS
    ), f"[Step B] channels: expected {_EXPECTED_CHANNELS}, got {channels!r}"

    fmt_raw: Any = info.get("format")
    assert isinstance(fmt_raw, dict), f"[Step B] ffprobe format not a dict: {fmt_raw!r}"
    fmt: dict[Any, Any] = fmt_raw  # pyright: ignore[reportUnknownVariableType]
    duration_str: Any = fmt.get("duration")
    assert isinstance(
        duration_str, str
    ), f"[Step B] missing duration in ffprobe output: {fmt!r}"
    duration = float(duration_str)
    delta = abs(duration - _DURATION_SECONDS)
    _helpers.log(
        f"[Step B] ffprobe: codec={codec} sample_rate={sample_rate_str} "
        f"channels={channels} duration={duration:.2f}s "
        f"(target={_DURATION_SECONDS:.2f}s, delta={delta:.2f}s)"
    )
    assert delta <= _DURATION_TOLERANCE_SECONDS, (
        f"[Step B] WAV duration {duration:.2f}s outside tolerance "
        f"+/-{_DURATION_TOLERANCE_SECONDS:.2f}s of target {_DURATION_SECONDS:.2f}s"
    )

    rms_db = _rms_dbfs(out_path)
    if math.isinf(rms_db):
        _helpers.log("[Step B] RMS = -inf dBFS (file is pure silence)")
    else:
        _helpers.log(f"[Step B] RMS = {rms_db:.2f} dBFS")


def _scenario() -> None:
    _helpers.log("calling vrcpilot.launch(no_vr=True)")
    vrcpilot.launch(no_vr=True)

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    _step_a_wav_file()
    _step_b_stdout_ffmpeg()


def main() -> int:
    return _helpers.run_scenario("cli_record_ffmpeg", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
