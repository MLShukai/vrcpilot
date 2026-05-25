"""E2E scenario: ``vrcpilot record --video`` piped into ``ffmpeg``.

Validates the Matroska self-describing pipe contract baked into the
unified ``vrcpilot record`` CLI: with no ``-o``, the command writes a
Matroska (MKV) byte stream to stdout. Because Matroska carries
codec, resolution, frame-rate and pixel-format in its own header,
``ffmpeg -i - <out>`` just works — there is no need for
``-f rawvideo`` / ``-video_size`` / ``-framerate`` flags on the
ffmpeg side.

The pipeline here is video-only (``--video``): ffmpeg copies the
H.264 elementary stream straight into a fresh ``.mp4`` container
(``-c:v copy``). No audio stream is muxed; the ``ffprobe`` round-trip
asserts exactly one video stream and zero audio streams.

Run with::

    just e2e-test cli_record_video_ffmpeg

VRChat is launched in Desktop mode at 1280x720 to match the other
capture-related scenarios. The encoded mp4 is written to
``_e2e_artifacts/cli_record_video_ffmpeg/<YYYYMMDD_HHMMSS>/cli_record_video_ffmpeg.mp4``
and a ``ffprobe`` round-trip verifies the file is a valid h264 mp4 with
roughly the expected duration.

The pipeline is wired with the standard "tee a Popen pipe" idiom: we
open ``ffmpeg`` first with ``stdin=PIPE``, hand its write-end to the
``vrcpilot record`` Popen as its ``stdout``, then close our own
reference to ``ffmpeg.stdin`` so ``vrcpilot`` becomes the sole writer.
When the recording duration elapses ``vrcpilot`` exits, the pipe sees
EOF, and ``ffmpeg`` flushes and exits cleanly.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import vrcpilot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

#: Wall-clock duration of the recording. Short enough to keep the e2e
#: scenario brisk; long enough that ffprobe can resolve a non-trivial
#: container duration.
_DURATION_SECONDS: float = 5.0

#: Target frame rate stored in the MKV header by ``vrcpilot record``
#: and faithfully copied to the mp4 by ffmpeg.
_TARGET_FPS: float = 30.0

#: Tolerance around ``_DURATION_SECONDS`` when checking the encoded
#: mp4's container duration. Wide enough to absorb worker-thread
#: warm-up jitter and the final partial-frame flush, narrow enough to
#: catch a "ffmpeg never received a frame" regression.
_DURATION_TOLERANCE_SECONDS: float = 1.5


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


def _scenario() -> None:
    _helpers.log(
        "calling vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)"
    )
    vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    out_path = (
        _helpers.scenario_dir("cli_record_video_ffmpeg") / "cli_record_video_ffmpeg.mp4"
    )

    # Matroska is self-describing, so ffmpeg picks codec/resolution/fps
    # out of the header. ``-c:v copy`` keeps the H.264 elementary
    # stream intact instead of re-encoding.
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "-",
        "-c:v",
        "copy",
        str(out_path),
    ]
    vrcpilot_cmd = [
        "uv",
        "run",
        "vrcpilot",
        "record",
        "--video",
        "--fps",
        f"{_TARGET_FPS}",
        "--duration",
        f"{_DURATION_SECONDS}",
    ]
    _helpers.log(f"$ {' '.join(vrcpilot_cmd)} | {' '.join(ffmpeg_cmd)}")

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
            f"  vrcpilot stderr: {vrc_stderr.decode(errors='replace').strip()}"
        )
    if ffmpeg_stderr:
        _helpers.log(
            f"  ffmpeg stderr: {ffmpeg_stderr.decode(errors='replace').strip()}"
        )

    assert vrc_rc == 0, f"vrcpilot record exit code: expected 0, got {vrc_rc}"
    assert ffmpeg_rc == 0, f"ffmpeg exit code: expected 0, got {ffmpeg_rc}"

    assert out_path.exists(), f"ffmpeg did not write {out_path}"
    size = out_path.stat().st_size
    assert size > 0, f"output mp4 is empty: {out_path}"
    _helpers.log(f"saved encoded video: {out_path} ({size} bytes)")

    info = _ffprobe_format(out_path)
    streams_raw: Any = info.get("streams", [])
    assert isinstance(streams_raw, list), f"ffprobe streams not a list: {streams_raw!r}"
    streams_list: list[Any] = streams_raw  # pyright: ignore[reportUnknownVariableType]
    video_streams = [
        s
        for s in streams_list
        if isinstance(s, dict) and s.get("codec_type") == "video"
    ]
    audio_streams = [
        s
        for s in streams_list
        if isinstance(s, dict) and s.get("codec_type") == "audio"
    ]
    assert (
        len(video_streams) == 1
    ), f"expected 1 video stream, got {len(video_streams)}: {streams_list!r}"
    assert (
        len(audio_streams) == 0
    ), f"expected 0 audio streams in --video mode, got {len(audio_streams)}"
    video_stream: dict[Any, Any] = video_streams[0]  # pyright: ignore[reportUnknownVariableType]
    codec: Any = video_stream.get("codec_name")
    assert codec == "h264", f"expected h264 codec, got {codec!r}"

    fmt_raw: Any = info.get("format")
    assert isinstance(fmt_raw, dict), f"ffprobe format not a dict: {fmt_raw!r}"
    fmt: dict[Any, Any] = fmt_raw  # pyright: ignore[reportUnknownVariableType]
    duration_str: Any = fmt.get("duration")
    assert isinstance(duration_str, str), f"missing duration in ffprobe output: {fmt!r}"
    duration = float(duration_str)
    delta = abs(duration - _DURATION_SECONDS)
    _helpers.log(
        f"ffprobe: codec={codec} duration={duration:.2f}s "
        f"(target={_DURATION_SECONDS:.2f}s, delta={delta:.2f}s)"
    )
    assert delta <= _DURATION_TOLERANCE_SECONDS, (
        f"mp4 duration {duration:.2f}s outside tolerance "
        f"+/-{_DURATION_TOLERANCE_SECONDS:.2f}s of target {_DURATION_SECONDS:.2f}s"
    )


def main() -> int:
    return _helpers.run_scenario("cli_record_video_ffmpeg", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
