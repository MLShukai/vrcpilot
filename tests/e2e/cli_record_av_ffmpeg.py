"""E2E scenario: ``vrcpilot record`` in default (video+audio) file mode.

Validates the ``--video`` / ``--audio``-both-absent code path of the
unified ``vrcpilot record`` CLI: with neither flag set, the command
records H.264 video and AAC audio into a single ``.mp4`` file (or
into a MKV stdout stream when ``-o`` is omitted). This scenario
exercises the file-mode side; for the stream-mode equivalents see
:mod:`cli_record_video_ffmpeg` and :mod:`cli_record_ffmpeg`.

Run with::

    just e2e-test cli_record_av_ffmpeg

VRChat is launched in Desktop mode at 1280x720 to match the other
capture-related scenarios. The recorded mp4 lands at
``_e2e_artifacts/cli_record_av_<YYYYMMDD_HHMMSS>.mp4`` and a
``ffprobe`` round-trip verifies exactly one h264 video stream and one
aac audio stream, with the container duration within tolerance of
the wall-clock duration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import vrcpilot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

#: Wall-clock duration of the recording. Short enough to keep the e2e
#: scenario brisk; long enough that ffprobe can resolve a non-trivial
#: container duration.
_DURATION_SECONDS: float = 5.0

#: Target frame rate stored in the mp4 container.
_TARGET_FPS: float = 30.0

#: Tolerance around ``_DURATION_SECONDS`` when checking the mp4's
#: container duration. Wide enough to absorb worker-thread warm-up
#: jitter and the final partial-frame flush, narrow enough to catch a
#: "vrcpilot never recorded anything" regression.
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

    _helpers.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = _helpers.ARTIFACT_DIR / f"cli_record_av_{stamp}.mp4"

    # Neither --video nor --audio: both modalities are recorded into
    # the same mp4 container.
    cmd = [
        "uv",
        "run",
        "vrcpilot",
        "record",
        "--fps",
        f"{_TARGET_FPS}",
        "--duration",
        f"{_DURATION_SECONDS}",
        "-o",
        str(out_path),
    ]
    _helpers.log(f"$ {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.stderr.strip():
        _helpers.log(f"  vrcpilot stderr: {result.stderr.strip()}")
    assert (
        result.returncode == 0
    ), f"vrcpilot record exit code: expected 0, got {result.returncode}"

    stdout_line = result.stdout.strip()
    expected_line = str(out_path.resolve())
    assert (
        stdout_line == expected_line
    ), f"stdout: expected exactly {expected_line!r}, got {stdout_line!r}"

    assert out_path.exists(), f"vrcpilot did not write {out_path}"
    size = out_path.stat().st_size
    assert size > 0, f"output mp4 is empty: {out_path}"
    _helpers.log(f"saved av mp4: {out_path} ({size} bytes)")

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
        len(streams_list) == 2
    ), f"expected exactly 2 streams (video + audio), got {len(streams_list)}: {streams_list!r}"
    assert (
        len(video_streams) == 1
    ), f"expected 1 video stream, got {len(video_streams)}: {streams_list!r}"
    assert (
        len(audio_streams) == 1
    ), f"expected 1 audio stream, got {len(audio_streams)}: {streams_list!r}"

    video_stream: dict[Any, Any] = video_streams[0]  # pyright: ignore[reportUnknownVariableType]
    video_codec: Any = video_stream.get("codec_name")
    assert video_codec == "h264", f"expected h264 video codec, got {video_codec!r}"

    audio_stream: dict[Any, Any] = audio_streams[0]  # pyright: ignore[reportUnknownVariableType]
    audio_codec: Any = audio_stream.get("codec_name")
    assert audio_codec == "aac", f"expected aac audio codec, got {audio_codec!r}"

    fmt_raw: Any = info.get("format")
    assert isinstance(fmt_raw, dict), f"ffprobe format not a dict: {fmt_raw!r}"
    fmt: dict[Any, Any] = fmt_raw  # pyright: ignore[reportUnknownVariableType]
    duration_str: Any = fmt.get("duration")
    assert isinstance(duration_str, str), f"missing duration in ffprobe output: {fmt!r}"
    duration = float(duration_str)
    delta = abs(duration - _DURATION_SECONDS)
    _helpers.log(
        f"ffprobe: video={video_codec} audio={audio_codec} "
        f"duration={duration:.2f}s "
        f"(target={_DURATION_SECONDS:.2f}s, delta={delta:.2f}s)"
    )
    assert delta <= _DURATION_TOLERANCE_SECONDS, (
        f"mp4 duration {duration:.2f}s outside tolerance "
        f"+/-{_DURATION_TOLERANCE_SECONDS:.2f}s of target {_DURATION_SECONDS:.2f}s"
    )


def main() -> int:
    return _helpers.run_scenario("cli_record_av_ffmpeg", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
