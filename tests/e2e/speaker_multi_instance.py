"""E2E scenario: per-PID audio capture with two VRChat instances.

Drives :class:`vrcpilot.speaker.SpeakerLoop` against **two concurrently
running VRChat clients** to confirm the per-PID PipeWire null-sink +
``sink_input_move`` design in :mod:`vrcpilot.speaker.linux` produces
an **independent** WAV stream for each VRChat process. Without per-PID
isolation both recordings would converge on the same mixed audio;
with it, each WAV carries the audio of exactly one VRChat instance.

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

Isolation assertion
-------------------

Phase A of the per-PID isolation fix elevates the PASS criteria from
"both files were written" to "the files contain *distinct* audio":

1. Both WAVs contain at least one frame (``frames > 0``).
2. The MD5 hash of each WAV's PCM data is **different**. Two
   bit-identical files are the exact symptom that motivated the Phase
   A rework (see ``CHANGELOG.md``), so this assertion is the primary
   detector for a regressed routing path.
3. The Pearson correlation of the two int16 sample streams (truncated
   to the shorter file's length, computed in float64) is below 0.95.
   MD5 catches bit-identical clones; correlation catches the looser
   "same audio with slight timing jitter" symptom that any future
   additive-duplication regression (a re-introduced bridge, a shared
   monitor source, etc.) could produce. Computed by hand rather than
   :func:`numpy.corrcoef` so a zero-norm signal returns ``0.0``
   instead of NaN.

RMS dBFS is still logged for each file but **not asserted**: VRChat's
absolute level depends on world / mixer / user settings, so it stays a
human-readable sanity number. The scenario also logs both PIDs,
both output paths, both MD5 hex digests, and the correlation
coefficient before the assertions run so a FAIL post-mortem can read
the observed values without re-running.

Artifacts land at
``_e2e_artifacts/speaker_multi_instance/<YYYYMMDD_HHMMSS>/<pid>.wav``.

Run with::

    just e2e-test speaker_multi_instance
"""

from __future__ import annotations

import hashlib
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
#: per-pid null-sink load + ``sink_input_move`` + post-verify on both
#: instances while keeping the scenario brisk enough to iterate on.
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


def _md5_of_wav(path: Path) -> str:
    """Return the MD5 hex digest of *path*'s PCM data chunk.

    Only the ``data`` chunk is hashed: the RIFF / ``fmt`` headers carry
    a length field that depends on the number of recorded frames, so
    hashing the whole file would mask audio-identity differences
    behind a header-length mismatch (or vice versa). ``wave.open`` is
    the real stdlib parser -- no 3rd-party surface is mocked.

    The hash is **not** used for any security-sensitive purpose; it is
    purely an audio-content equality probe, so ``usedforsecurity=False``
    silences linters that would otherwise flag MD5.
    """
    with wave.open(str(path), "rb") as reader:
        n_frames = reader.getnframes()
        raw = reader.readframes(n_frames)
    return hashlib.md5(raw, usedforsecurity=False).hexdigest()


def _read_int16_samples(path: Path) -> NDArray[np.int16]:
    """Return *path*'s PCM frames as a 1-D ``int16`` array.

    Stereo (2-channel) frames are kept interleaved; the consumer only
    needs a comparable sample stream, not channel-separated views. Empty
    files return an empty array rather than raising so the correlation
    helper can short-circuit on zero norm.
    """
    with wave.open(str(path), "rb") as reader:
        n_frames = reader.getnframes()
        raw = reader.readframes(n_frames)
    if n_frames == 0 or not raw:
        return np.zeros((0,), dtype=np.int16)
    return np.frombuffer(raw, dtype=np.int16)


def _pearson_correlation(a: NDArray[np.int16], b: NDArray[np.int16]) -> float:
    """Pearson correlation of two ``int16`` sample arrays.

    Truncates both arrays to the shorter length so a one-frame size
    mismatch (e.g. the recorders started a tick apart) does not break
    the calculation. Computed in ``float64`` with explicit mean
    subtraction and dot-product / norm so a degenerate zero-norm input
    returns ``0.0`` rather than NaN. :func:`numpy.corrcoef` would
    return NaN in that case, which is harder to assert against -- the
    explicit form is the more useful primitive for an isolation check.
    """
    n = min(a.size, b.size)
    if n == 0:
        return 0.0
    x = a[:n].astype(np.float64)
    y = b[:n].astype(np.float64)
    x = x - x.mean()
    y = y - y.mean()
    nx = float(np.linalg.norm(x))
    ny = float(np.linalg.norm(y))
    if nx == 0.0 or ny == 0.0:
        return 0.0
    return float(np.dot(x, y) / (nx * ny))


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

    # Frame counts are observed per-PID and reported before the
    # isolation assertions so a FAIL post-mortem has the raw numbers.
    frames_per_pid: dict[int, int] = {}
    for pid, path in ((pid_a, path_a), (pid_b, path_b)):
        rms_db = _rms_dbfs(path)
        rms_label = (
            "-inf dBFS (pure silence)" if math.isinf(rms_db) else f"{rms_db:.2f} dBFS"
        )
        frames = results[pid].get("frames", 0)
        frames_per_pid[pid] = frames
        _helpers.log(f"pid={pid} frames={frames} -> {path} (RMS = {rms_label})")

    # --- Isolation assertions ---------------------------------------
    # See the module docstring's "Isolation assertion" section for why
    # each of these must hold. Log every observation *before* the
    # assert so a failure leaves the actual MD5 / correlation values
    # in the run log.
    frames_a = frames_per_pid[pid_a]
    frames_b = frames_per_pid[pid_b]
    assert frames_a > 0, f"pid={pid_a} recorded 0 frames; capture did not run"
    assert frames_b > 0, f"pid={pid_b} recorded 0 frames; capture did not run"

    md5_a = _md5_of_wav(path_a)
    md5_b = _md5_of_wav(path_b)
    _helpers.log(f"pid={pid_a} md5={md5_a}")
    _helpers.log(f"pid={pid_b} md5={md5_b}")

    samples_a = _read_int16_samples(path_a)
    samples_b = _read_int16_samples(path_b)
    corr = _pearson_correlation(samples_a, samples_b)
    _helpers.log(f"pearson correlation (pid={pid_a} vs pid={pid_b}) = {corr:.3f}")

    assert md5_a != md5_b, (
        f"both WAVs are bit-identical (MD5={md5_a}) — per-PID isolation "
        f"failed; the two recordings captured the same audio stream"
    )
    assert abs(corr) < 0.95, (
        f"Pearson correlation {corr:.3f} ≥ 0.95 — WAVs look like the "
        f"same audio (md5_a={md5_a}, md5_b={md5_b}); per-PID isolation "
        f"is leaking even though the byte streams differ"
    )

    _helpers.log(
        "scenario complete; per-PID isolation asserts passed. Play "
        "both WAVs back to spot-check that each one matches its "
        "instance's audio (audible content is still a human check)."
    )


def main() -> int:
    return _helpers.run_scenario("speaker_multi_instance", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
