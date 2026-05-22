"""E2E scenario: drive SpeakerLoop and capture VRChat audio to WAV.

Drives :class:`vrcpilot.speaker.SpeakerLoop` against a real running
VRChat client to confirm that the proc-tap process-loopback backend
plus the loop and a Python-side PyAV recorder pipeline produces a
playable WAV file end to end. The scenario opens
``SpeakerLoop(callback, chunk_seconds=0.05)``, sleeps the wall-clock
duration on the main thread while the worker thread writes each
chunk through an e2e-local PyAV recorder
(:class:`_pyav_recorder.WavAudioRecorder`), and logs the RMS level
of the resulting file so a human can sanity check the recorded
signal.

This scenario is intentionally **CLI-independent**: it does not
shell out to ``vrcpilot record`` or import the CLI's internal muxer.
That keeps the e2e suite stable against CLI rearrangement and doubles
as a worked example of "compose your own PyAV writer around
SpeakerLoop" for downstream library users.

Run with::

    just e2e-test speaker

VRChat is launched in Desktop mode with ``no_vr=True`` so the scenario
can run on machines without an HMD. The recording is written to
``_e2e_artifacts/speaker_<YYYYMMDD_HHMMSS>.wav``.

NOTE: on this first pass the scenario does not assert any RMS
threshold — VRChat's default world audio level varies between
machines (volume mixer, master output, world choice). The logged
``RMS = ... dBFS`` value is the observation we'll use to pick a
reasonable lower bound in a follow-up commit.
"""

from __future__ import annotations

import math
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

import vrcpilot
from vrcpilot.speaker import SpeakerLoop

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402
import _pyav_recorder  # noqa: E402

#: Wall-clock duration of the recording. 5 s is long enough to expose
#: backend startup hiccups while keeping the scenario brisk.
_DURATION_SECONDS: float = 5.0

#: SpeakerLoop tick period. 50 ms matches the proc-tap chunk cadence
#: (~10-20 ms) and the documented default; keeping it explicit makes
#: the scenario self-documenting.
_CHUNK_SECONDS: float = 0.05


class _WavRecorderCallback:
    """Callback target: forwards chunks to the recorder and tallies frames.

    The state is only touched from the SpeakerLoop worker thread; the
    main thread reads :attr:`frames_written` after ``SpeakerLoop.stop``
    has joined the worker, so no lock is required.
    """

    def __init__(self, recorder: _pyav_recorder.WavAudioRecorder) -> None:
        self._recorder = recorder
        self.frames_written: int = 0

    def on_chunk(self, chunk: NDArray[np.float32]) -> None:
        # Empty reads (silence ticks) are valid; the recorder's
        # ``write`` is a no-op for ``N == 0`` so we can forward
        # unconditionally.
        self._recorder.write(chunk)
        self.frames_written += int(chunk.shape[0])


def _rms_dbfs(path: Path) -> float:
    """Return the RMS level of *path* in dBFS, or ``-inf`` for pure silence.

    The WAV is 16-bit signed PCM (see
    :class:`_pyav_recorder.WavAudioRecorder`); we read the entire
    file and compute the RMS over both channels combined. A perfectly
    silent file (all zero samples) maps to ``-inf`` rather than
    producing a math-domain error, which is the natural meaning of
    "no signal at all".
    """
    with wave.open(str(path), "rb") as reader:
        n_frames = reader.getnframes()
        n_channels = reader.getnchannels()
        raw = reader.readframes(n_frames)

    if n_frames == 0:
        return float("-inf")

    samples = np.frombuffer(raw, dtype=np.int16)
    if samples.size == 0:
        return float("-inf")

    # Combine all channels; we want a single scalar level, not a
    # per-channel breakdown, and stereo VRChat audio with one silent
    # side should not look louder than the same content in mono.
    del n_channels  # documented above; not needed for the calculation
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    if rms <= 0.0:
        return float("-inf")
    # Full-scale int16 is 32768 in magnitude (``[-32768, 32767]``).
    return 20.0 * math.log10(rms / 32768.0)


def _scenario() -> None:
    _helpers.log("calling vrcpilot.launch(no_vr=True)")
    vrcpilot.launch(no_vr=True)

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    _helpers.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = _helpers.ARTIFACT_DIR / f"speaker_{stamp}.wav"

    _helpers.log(
        f"opening SpeakerLoop(chunk_seconds={_CHUNK_SECONDS:.3f}) and recording "
        f"for {_DURATION_SECONDS:.1f}s to {out_path}"
    )

    with _pyav_recorder.WavAudioRecorder(out_path) as recorder:
        callback = _WavRecorderCallback(recorder)
        with SpeakerLoop(callback.on_chunk, chunk_seconds=_CHUNK_SECONDS) as loop:
            loop.start()
            time.sleep(_DURATION_SECONDS)
            loop.stop()

        frames_written = callback.frames_written
        sample_count = recorder.sample_count

    _helpers.log(
        f"saved wav: {out_path} "
        f"(callback_frames={frames_written} recorder_samples={sample_count})"
    )

    # First-pass observation only: no threshold assertion yet (see
    # module docstring). The number is what we'll use to choose a
    # reasonable floor in a follow-up commit.
    rms_db = _rms_dbfs(out_path)
    if math.isinf(rms_db):
        _helpers.log("RMS = -inf dBFS (file is pure silence)")
    else:
        _helpers.log(f"RMS = {rms_db:.2f} dBFS")


def main() -> int:
    return _helpers.run_scenario("speaker", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
