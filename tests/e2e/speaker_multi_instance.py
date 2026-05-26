"""E2E scenario: per-PID audio capture with two VRChat instances running.

Validates that :class:`vrcpilot.speaker.SpeakerLoop` produces an
**independent** WAV stream for each VRChat process when the user has
two clients running side by side. The scenario assumes the user
manually started two VRChat instances first (the easiest path on Linux
is two separate Steam ``-profile=`` invocations or two ``umu-run``
shells) — see ``docs`` / the plan for instructions. If only one
instance is found the scenario exits with a clear skip-style message
instead of running half-blind.

Pipeline per VRChat instance, run concurrently on background threads:

* ``SpeakerLoop(callback, chunk_seconds=0.05, pid=<that-pid>)``
* a :class:`_pyav_recorder.WavAudioRecorder` writing one WAV per PID
* an RMS-dBFS readout for each WAV after the worker thread joins

The captured WAVs land in
``_e2e_artifacts/speaker_multi_instance/<YYYYMMDD_HHMMSS>/<pid>.wav``.
Inspect them by ear (or with ``aplay``) to confirm each file matches
the audio of its respective world, rather than a mixed-down blend.
"""

from __future__ import annotations

import math
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from vrcpilot.process.pid import find_pids
from vrcpilot.speaker import SpeakerLoop

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402
import _pyav_recorder  # noqa: E402

#: Wall-clock duration of each recording. 10 s comfortably outlasts
#: per-pid sink load + sink_input move + loopback creation while
#: keeping the scenario brisk enough to iterate on.
_DURATION_SECONDS: float = 10.0

#: SpeakerLoop tick period. Matches ``tests/e2e/speaker.py`` so the
#: scenarios share their failure modes.
_CHUNK_SECONDS: float = 0.05


class _WavRecorderCallback:
    """Per-PID callback: forwards chunks to the recorder and tallies frames.

    State is only touched from one SpeakerLoop worker thread per PID;
    the main thread reads :attr:`frames_written` after ``SpeakerLoop.stop``
    joins, so no lock is required.
    """

    def __init__(self, recorder: _pyav_recorder.WavAudioRecorder) -> None:
        self._recorder = recorder
        self.frames_written: int = 0

    def on_chunk(self, chunk: NDArray[np.float32]) -> None:
        # Empty reads (silence ticks) are valid; the recorder's
        # ``write`` is a no-op for ``N == 0``.
        self._recorder.write(chunk)
        self.frames_written += int(chunk.shape[0])


def _rms_dbfs(path: Path) -> float:
    """Return the RMS level of *path* in dBFS, or ``-inf`` for pure silence.

    Mirrors :func:`tests.e2e.speaker._rms_dbfs` so both scenarios print
    comparable numbers.
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
    return 20.0 * math.log10(rms / 32768.0)


def _record_one(pid: int, out_path: Path) -> int:
    """Record one PID for ``_DURATION_SECONDS`` and return frame count.

    Used as a thread target so two PIDs are recorded concurrently. The
    SpeakerLoop / recorder context managers fully release PipeWire
    resources before returning so a thread failure does not leak a null-
    sink onto the daemon.
    """
    with _pyav_recorder.WavAudioRecorder(out_path) as recorder:
        callback = _WavRecorderCallback(recorder)
        with SpeakerLoop(
            callback.on_chunk, chunk_seconds=_CHUNK_SECONDS, pid=pid
        ) as loop:
            loop.start()
            time.sleep(_DURATION_SECONDS)
            loop.stop()
        return callback.frames_written


def _scenario() -> None:
    pids = find_pids()
    if len(pids) < 2:
        _helpers.log(
            f"scenario requires at least 2 VRChat instances, found {len(pids)}; "
            "start a second VRChat (e.g. via a separate Steam profile) and "
            "re-run."
        )
        # The scenario runner uses the return code; ``run_scenario``
        # only fails on raised exceptions, so an early return with a
        # clear log message is the right shape for a soft skip here.
        return

    # Two PIDs is the documented scenario shape. If three or more are
    # running we still only record the first two; the goal is per-pid
    # isolation, not exhaustive coverage.
    pid_a, pid_b = pids[0], pids[1]
    _helpers.log(f"recording two VRChat PIDs in parallel: {pid_a}, {pid_b}")

    _helpers.warmup()

    scenario_dir = _helpers.scenario_dir("speaker_multi_instance")
    path_a = scenario_dir / f"{pid_a}.wav"
    path_b = scenario_dir / f"{pid_b}.wav"

    results: dict[int, int] = {}
    errors: dict[int, BaseException] = {}

    def runner(pid: int, path: Path) -> None:
        try:
            results[pid] = _record_one(pid, path)
        except BaseException as exc:  # noqa: BLE001
            errors[pid] = exc

    thread_a = threading.Thread(
        target=runner, args=(pid_a, path_a), name=f"recorder-{pid_a}"
    )
    thread_b = threading.Thread(
        target=runner, args=(pid_b, path_b), name=f"recorder-{pid_b}"
    )
    thread_a.start()
    thread_b.start()
    thread_a.join()
    thread_b.join()

    if errors:
        for pid, exc in errors.items():
            _helpers.log(f"recorder for pid={pid} failed: {exc!r}")
        # Re-raise the first error so ``run_scenario`` surfaces a
        # non-zero exit code rather than silently succeeding.
        first_pid = next(iter(errors))
        raise errors[first_pid]

    for pid, path in ((pid_a, path_a), (pid_b, path_b)):
        rms_db = _rms_dbfs(path)
        rms_label = (
            "-inf dBFS (pure silence)" if math.isinf(rms_db) else (f"{rms_db:.2f} dBFS")
        )
        _helpers.log(f"pid={pid} frames={results[pid]} -> {path} (RMS = {rms_label})")

    _helpers.log(
        "scenario complete; play both WAVs back to confirm each file "
        "matches its world's audio rather than a mixed blend."
    )


def main() -> int:
    return _helpers.run_scenario("speaker_multi_instance", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
