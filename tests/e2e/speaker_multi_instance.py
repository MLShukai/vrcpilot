"""E2E scenario: per-PID audio capture with two VRChat instances.

Drives :class:`vrcpilot.speaker.SpeakerLoop` against **two concurrently
running VRChat clients** to confirm the per-PID PipeWire null-sink +
module-loopback + ``sink_input_move`` design in
:mod:`vrcpilot.speaker.linux` produces an **independent** WAV stream
for each VRChat process. Without per-PID isolation both recordings
would converge on the same mixed audio; with it, each WAV carries the
audio of exactly one VRChat instance.

Two-instance launch
-------------------

The scenario starts both VRChat clients itself via :func:`vrcpilot.launch`:

* ``profile=0`` — the default slot that reuses Steam's own
  ``compatdata/<app_id>/pfx`` as the Wine prefix on Linux.
* ``profile=1`` — seeds a per-profile prefix under
  ``$XDG_DATA_HOME/vrcpilot/profiles/1/wineprefix`` so the second
  instance does not collide with the first on Wine prefix locks.

See :func:`vrcpilot.process.launch.launch` for the wineprefix-per-profile
contract. ``no_vr=True`` lets the scenario run on machines without an
HMD; we only need audio, not stereo rendering.

Concurrent recording
--------------------

Once both PIDs are settled (a single :func:`_helpers.warmup` covers
both), the scenario opens one
``SpeakerLoop(callback, chunk_seconds=0.05, pid=<pid>)`` per PID on a
background thread, sleeps the recording duration on the main thread,
then joins. The per-PID :class:`_pyav_recorder.WavAudioRecorder`
context manager guarantees PipeWire resources are released even if a
worker thread raises.

Observation, not threshold assertion
------------------------------------

VRChat's audio level depends on world / volume mixer / user settings,
so this scenario follows :mod:`tests.e2e.speaker`'s policy of logging
the RMS dBFS for each WAV rather than asserting a hard floor. PASS
means both recordings completed and the per-PID files were written
without an exception escaping the scenario body; a human spot-checks
the audible content by playing the WAVs back.

Artifacts land at
``_e2e_artifacts/speaker_multi_instance/<YYYYMMDD_HHMMSS>/<pid>.wav``.

Run with::

    just e2e-test speaker_multi_instance
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

import vrcpilot
from vrcpilot.speaker import SpeakerLoop

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402
import _pyav_recorder  # noqa: E402

#: Wall-clock duration of each recording. 10 s comfortably outlasts
#: per-pid sink load + sink_input move + loopback creation while
#: keeping the scenario brisk enough to iterate on.
_DURATION_SECONDS: float = 10.0

#: SpeakerLoop tick period. Matches :mod:`tests.e2e.speaker` so the two
#: scenarios share their failure modes.
_CHUNK_SECONDS: float = 0.05

#: Small wait between the two ``vrcpilot.launch`` calls. ``launch``
#: already blocks until it sees a new PID, but giving Steam / umu /
#: Proton a beat to settle the first prefix lock before the second
#: spawn races for the second prefix reduces transient races on slow
#: hosts. Kept short because ``launch``'s own ``_wait_for_new_pid``
#: still does the real waiting.
_INTER_LAUNCH_SLEEP_SECONDS: float = 2.0


class _WavRecorderCallback:
    """Per-PID callback: forwards chunks to the recorder and tallies frames.

    State is only touched from one SpeakerLoop worker thread per PID;
    the main thread reads :attr:`frames_written` after ``SpeakerLoop.stop``
    has joined the worker, so no lock is required.
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
    # Full-scale int16 is 32768 in magnitude (``[-32768, 32767]``).
    return 20.0 * math.log10(rms / 32768.0)


def _record_one(pid: int, out_path: Path, result: dict[str, int]) -> None:
    """Record one VRChat PID for ``_DURATION_SECONDS`` to *out_path*.

    Runs on a worker thread so two PIDs can be recorded concurrently.
    On exit the SpeakerLoop / WavAudioRecorder context managers have
    fully released PipeWire resources, so a thread failure cannot leak
    a null-sink onto the daemon. Frame count is written into *result*
    under ``"frames"`` for the main thread to read after ``join``.
    """
    with _pyav_recorder.WavAudioRecorder(out_path) as recorder:
        callback = _WavRecorderCallback(recorder)
        with SpeakerLoop(
            callback.on_chunk, chunk_seconds=_CHUNK_SECONDS, pid=pid
        ) as loop:
            loop.start()
            time.sleep(_DURATION_SECONDS)
            loop.stop()
        result["frames"] = callback.frames_written


def _launch_instance(profile: int) -> int:
    """Launch a VRChat instance with ``--profile=profile`` and return its PID.

    Raises ``RuntimeError`` if :func:`vrcpilot.launch` returns ``None``
    (timed out waiting for the new PID), so the scenario fails loudly
    rather than handing ``None`` to ``SpeakerLoop`` later.
    """
    _helpers.log(f"calling vrcpilot.launch(profile={profile}, no_vr=True)")
    pid = vrcpilot.launch(profile=profile, no_vr=True)
    if pid is None:
        raise RuntimeError(
            f"vrcpilot.launch(profile={profile}) timed out before a new "
            "VRChat PID was observed"
        )
    _helpers.log(f"VRChat started (profile={profile}, pid={pid})")
    return pid


def _scenario() -> None:
    pid_a = _launch_instance(profile=0)
    # Stagger the second spawn slightly so the first instance has time
    # to acquire its wineprefix lock before the second one starts its
    # own. ``launch`` blocks until a new PID is observed, so this sleep
    # is purely about lock-acquisition smoothness on the first spawn,
    # not about waiting for the PID itself.
    time.sleep(_INTER_LAUNCH_SLEEP_SECONDS)
    pid_b = _launch_instance(profile=1)
    if pid_a == pid_b:
        raise RuntimeError(
            f"both launch() calls returned the same PID ({pid_a}); the "
            "second instance failed to spawn or PID detection collapsed "
            "the two onto one process"
        )

    _helpers.warmup()

    out_dir = _helpers.scenario_dir("speaker_multi_instance")
    path_a = out_dir / f"{pid_a}.wav"
    path_b = out_dir / f"{pid_b}.wav"

    _helpers.log(
        f"recording two VRChat PIDs in parallel: "
        f"pid={pid_a} -> {path_a}, pid={pid_b} -> {path_b} "
        f"(duration={_DURATION_SECONDS:.1f}s, chunk_seconds={_CHUNK_SECONDS:.3f})"
    )

    results: dict[int, dict[str, int]] = {pid_a: {}, pid_b: {}}
    errors: dict[int, BaseException] = {}

    def runner(pid: int, path: Path) -> None:
        try:
            _record_one(pid, path, results[pid])
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
            "-inf dBFS (pure silence)" if math.isinf(rms_db) else f"{rms_db:.2f} dBFS"
        )
        frames = results[pid].get("frames", 0)
        _helpers.log(f"pid={pid} frames={frames} -> {path} (RMS = {rms_label})")

    _helpers.log(
        "scenario complete; play both WAVs back to confirm each file "
        "matches its instance's audio rather than a mixed blend."
    )


def main() -> int:
    return _helpers.run_scenario("speaker_multi_instance", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
