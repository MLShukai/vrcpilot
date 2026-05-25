"""E2E scenario: drive CaptureLoop at 30fps and save the output as mp4.

Drives :class:`vrcpilot.CaptureLoop` against a real running VRChat
client to confirm the fixed-FPS Python API works end-to-end. The
scenario opens ``CaptureLoop(callback, fps=30.0)``, sleeps the
wall-clock duration on the main thread while the worker thread writes
each frame through a small e2e-local PyAV recorder
(:class:`_pyav_recorder.Mp4VideoRecorder`), and logs the per-frame
interval distribution so a human can sanity-check the cadence.

This scenario is intentionally **CLI-independent**: it does not
shell out to ``vrcpilot record`` or import the CLI's internal muxer.
That keeps the e2e suite stable against CLI rearrangement and doubles
as a worked example of "compose your own PyAV writer around
CaptureLoop" for downstream library users.

The mp4 is muxed at the same target fps used to drive the loop; mp4
playback duration should therefore match the recorded wall-clock
duration. ``measured_fps`` in the log line is computed from actual
inter-callback intervals and indicates how closely CaptureLoop is
hitting the target.

Run with::

    just e2e-test capture

VRChat is launched in Desktop mode with a 1280x720 window so the
captured frames land at a familiar resolution and so cropping
behaviour is visible in the output (any desktop bleed indicates a
regression -- the WGC / X11 Composite paths capture the window region
only).

The captured video is written to
``_e2e_artifacts/capture/<YYYYMMDD_HHMMSS>/capture.mp4``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

import vrcpilot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402
import _pyav_recorder  # noqa: E402

#: Wall-clock duration of the recording. ~10 s is long enough to see
#: the cadence and any glitches, short enough that the e2e scenario
#: stays brisk.
_DURATION_SECONDS: float = 10.0

#: Target frame rate for both CaptureLoop and the mp4 container.
_TARGET_FPS: float = 30.0


class _FrameRecorder:
    """Callback target: forwards frames to the recorder and logs intervals.

    Both attributes are touched only from the CaptureLoop worker
    thread; the main thread reads them after :meth:`CaptureLoop.stop`
    has joined the worker, so no lock is required.
    """

    def __init__(self, recorder: _pyav_recorder.Mp4VideoRecorder) -> None:
        self._recorder = recorder
        self._last_t: float | None = None
        self.intervals: list[float] = []

    def on_frame(self, frame: NDArray[np.uint8]) -> None:
        now = time.monotonic()
        if self._last_t is not None:
            self.intervals.append(now - self._last_t)
        self._last_t = now
        self._recorder.write(frame)


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

    out_path = _helpers.scenario_dir("capture") / "capture.mp4"

    _helpers.log(
        f"opening CaptureLoop(fps={_TARGET_FPS:.1f}) and recording for "
        f"{_DURATION_SECONDS:.1f}s to {out_path}"
    )

    with _pyav_recorder.Mp4VideoRecorder(out_path, _TARGET_FPS) as recorder:
        callback = _FrameRecorder(recorder)
        with vrcpilot.CaptureLoop(callback.on_frame, fps=_TARGET_FPS) as loop:
            loop.start()
            time.sleep(_DURATION_SECONDS)
            loop.stop()

        frame_count = recorder.frame_count

    _helpers.log(f"saved video: {out_path} (frames={frame_count})")

    intervals = callback.intervals
    if intervals:
        # All log output stays in ASCII to dodge the cp932 encode trap
        # on Windows (CLAUDE.md "Windows 日本語環境（cp932）の非 ASCII
        # 出力").
        avg = sum(intervals) / len(intervals)
        measured_fps = 1.0 / avg if avg > 0 else float("inf")
        _helpers.log(
            "frame intervals (s): "
            f"min={min(intervals):.4f} "
            f"max={max(intervals):.4f} "
            f"avg={avg:.4f} "
            f"count={len(intervals)} "
            f"measured_fps={measured_fps:.2f} "
            f"target_fps={_TARGET_FPS:.2f}"
        )


def main() -> int:
    return _helpers.run_scenario("capture", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
