"""E2E scenario: cross-platform Mic loopback verification.

Drives :class:`vrcpilot.mic.Mic` against the real :mod:`soundcard`
backend (libpulse on Linux, WASAPI on Windows) and confirms that audio
written to the platform's virtual mic device re-emerges on the matching
loopback recording device. On Windows this resolves to VB-Audio Virtual
Cable (``CABLE Input`` -> ``CABLE Output``); on Linux it resolves to the
PipeWire ``VRCPilotMic`` null-sink registered by
``vrcpilot linux-mic register`` (whose ``Monitor of VRCPilot Virtual Mic``
source matches the same ``VRCPilotMic`` substring).

Unlike every other scenario in this directory, this one does **not** launch
VRChat: the test is about the mic-modality output path (Python ->
soundcard -> virtual mic -> soundcard input) and VRChat's own audio
routing is irrelevant. ``vrcpilot record`` (proc-tap) is intentionally not
used because it captures VRChat output audio via process-loopback, which is
a different code path from the mic output stream this scenario exercises.

Strategy:

* Resolve the playback and record substrings via the OS default + optional
  env overrides:

  * Playback substring: ``$VRCPILOT_MIC_DEVICE`` if set, otherwise
    :func:`vrcpilot.mic.default_device_name`.
  * Record substring: ``$VRCPILOT_MIC_LOOPBACK_DEVICE`` if set, otherwise
    derived from the playback substring via a small in-scenario map.

  Both env vars are picked up automatically by ``just e2e-test`` via the
  ``set dotenv-load := true`` line in the project ``justfile``.
* Probe :func:`soundcard.all_speakers` / :func:`soundcard.all_microphones`
  for both substrings. If either is missing the scenario PASSes with a
  "skipped" note, mirroring how the codebase handles platform-only deps
  in unit tests via ``pytest.skip``. The same applies if :mod:`soundcard`
  itself is not installed (or libpulse is missing), or if the Linux setup
  step (``vrcpilot linux-mic register``) has not been run.
* A background thread opens ``microphone.recorder()`` on the record
  device and pulls fixed-size blocks in a tight loop, appending each
  block to a list. ``soundcard``'s recorder is a pull-mode API (unlike
  PortAudio's push-mode callback), so the thread itself drives the cadence
  via :meth:`record`; a :class:`threading.Event` signals the thread to
  exit when the main thread closes the context. No lock is needed: the
  main thread only reads ``self._chunks`` after the worker has been
  joined.
* The main thread plays a 1 s 440 Hz sine, stereo, in 100 ms chunks.
  Sample rate is fixed to 48 kHz so both ends agree without negotiation.
* Verification is intentionally lenient on this first pass:

  * RMS of the recorded buffer must clear an "obvious silence" floor.
  * An FFT of the recorded signal must show its strongest bin at the
    played frequency (440 Hz +/- one bin), confirming the signal that
    transited the loopback is the sine we generated rather than noise or
    a different upstream source. A tight latency / amplitude check
    will be added once real-hardware numbers are observed.

Run with::

    just e2e-test mic

Prerequisites (host-dependent):

* Windows: VB-Audio Virtual Cable installed
  (https://vb-audio.com/Cable/) so ``CABLE Input`` / ``CABLE Output``
  show up under WASAPI.
* Linux: ``vrcpilot linux-mic register`` has been run so the
  ``VRCPilotMic`` PipeWire null-sink (plus its ``Monitor of VRCPilot
  Virtual Mic`` source) exists, and ``libpulse`` is available so
  :mod:`soundcard` can talk to PipeWire-pulse.
* ``soundcard`` installed in the active uv environment (it is a
  project-wide dependency now, so ``uv sync`` covers it on every OS).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

#: Env var (e2e-only) overriding the substring used to locate the
#: recording side of the loopback. The vrcpilot library does **not** read
#: this variable; it exists solely so a developer with a non-default
#: virtual-mic setup can still drive this scenario. The playback side is
#: overridden via ``$VRCPILOT_MIC_DEVICE`` (``vrcpilot.mic.base.DEVICE_ENV_VAR``),
#: which the library *does* read.
_LOOPBACK_DEVICE_ENV_VAR = "VRCPILOT_MIC_LOOPBACK_DEVICE"


def _default_loopback_record() -> dict[str, str]:
    """Map playback substring -> matching recording substring.

    Keyed by the canonical playback names produced by
    :func:`vrcpilot.mic.default_device_name`. For Linux the monitor
    source PipeWire creates for the ``VRCPilotMic`` null-sink is
    surfaced by soundcard with ``id="VRCPilotMic.monitor"``; the
    bare sink name does not match it because
    :func:`soundcard.get_microphone` does an exact-id lookup before
    falling back to a fuzzy name scan. The Linux key is read from
    ``vrcpilot.mic.VIRTUAL_MIC_SINK_NAME`` so the e2e harness never
    drifts away from the production constant, and the value appends
    the explicit ``.monitor`` suffix the null-sink convention exposes.

    Built lazily inside a function so the ``vrcpilot.mic`` import (and
    its OS-conditional sub-imports) is deferred until ``main()`` runs
    -- collection still works on hosts where the package fails to
    construct module-level state.
    """
    from vrcpilot.mic import VIRTUAL_MIC_SINK_NAME

    return {
        "CABLE Input": "CABLE Output",
        VIRTUAL_MIC_SINK_NAME: f"{VIRTUAL_MIC_SINK_NAME}.monitor",
    }


#: Sample rate / channel count for the loopback. 48 kHz matches the
#: project's pinned :data:`vrcpilot.mic.SAMPLE_RATE`. Stereo is passed
#: explicitly to ``Mic(..., channels=_CHANNELS)`` so the playback
#: stream opens in stereo at construction time.
_SAMPLE_RATE = 48000
_CHANNELS = 2

#: Recorder block size in frames. 480 frames at 48 kHz is 10 ms, which
#: matches the chunk cadence soundcard itself uses internally and keeps
#: the pull-mode ``record()`` loop tight enough that the stop event is
#: observed within one tick of being set.
_RECORDER_BLOCKSIZE = int(_SAMPLE_RATE * 0.01)

#: Sine tone parameters. 440 Hz (A4) is well within both VB-Cable's and
#: PipeWire's pass band and far from DC, so any high-pass on the path
#: leaves it intact.
_FREQUENCY_HZ = 440.0
_TONE_SECONDS = 1.0
_CHUNK_SECONDS = 0.1

#: Lead-in time the recorder gets before playback starts. Long enough
#: for the recorder thread to enter its first ``record()`` call; short
#: enough that the head of the sine still lands inside the recording
#: buffer.
_RECORD_LEAD_IN_SECONDS = 0.2

#: Trailing silence captured after playback ends so the cross-correlation
#: window covers the whole tone even if the backend adds a few hundred ms
#: of latency on either side.
_RECORD_TAIL_SECONDS = 0.4

#: RMS floor below which we declare the recording "obviously silent".
#: Virtual mics typically pass the signal at unity, so a 0.7-amplitude
#: sine should land an order of magnitude above this. Picked
#: conservatively for the first pass; tighten once real-hardware
#: numbers are in.
_RMS_SILENCE_FLOOR = 0.01

#: Sine amplitude (linear). 0.7 leaves headroom under the +/-1.0 float
#: rail so any small gain stage on the path cannot clip the signal,
#: which would flatten the cross-correlation peak.
_SINE_AMPLITUDE = 0.7

#: How many FFT bins of slack we allow around the expected 440 Hz peak
#: when matching the recording's strongest frequency. One bin at
#: ~1 Hz resolution (FFT of >1 s of audio at 48 kHz) accommodates
#: rounding without admitting a totally unrelated band.
_FREQUENCY_BIN_TOLERANCE = 2


def _try_import_soundcard() -> Any | None:
    """Return the :mod:`soundcard` module, or ``None`` on failure.

    Logs the failure and returns ``None`` so callers can treat both
    "soundcard not installed" and "libpulse not loadable" the same way:
    a single "skipped" branch in :func:`_scenario`. ``OSError`` covers
    the Linux libpulse-missing case (soundcard raises it when the
    shared library cannot be dlopened). Consolidating the try/except
    in one helper keeps the 4 callsites that previously duplicated this
    block down to one.
    """
    try:
        import soundcard as sc  # pyright: ignore[reportMissingTypeStubs]
    except ImportError as exc:
        _helpers.log(f"soundcard not installed: {exc!r}")
        return None
    except OSError as exc:
        _helpers.log(f"soundcard import failed (libpulse missing?): {exc!r}")
        return None
    return sc


def _query_speakers() -> list[Any] | None:
    """Return soundcard's speaker list, or ``None`` if soundcard missing.

    Also returns ``None`` when ``all_speakers()`` itself raises
    ``RuntimeError`` -- some libpulse builds dlopen lazily on the first
    enumeration and the failure only surfaces here. Treating that as
    "skip" matches the import-failure path the caller already handles.
    """
    sc = _try_import_soundcard()
    if sc is None:
        return None
    try:
        return list(sc.all_speakers())  # pyright: ignore[reportUnknownMemberType]
    except (OSError, RuntimeError) as exc:
        _helpers.log(f"sc.all_speakers() failed: {exc!r}")
        return None


def _query_microphones() -> list[Any] | None:
    """Return soundcard's microphone list, or ``None`` if soundcard missing.

    Mirrors :func:`_query_speakers` so the caller can probe each side of
    the loopback independently. ``include_loopback=True`` keeps
    PulseAudio monitor sources (e.g. the ``VRCPilotMic.monitor``
    source registered by ``vrcpilot linux-mic register``) in the
    enumeration -- they are filtered out of the default
    :func:`soundcard.all_microphones` view, which made the Linux
    loopback scenario fail to find anything earlier. ``RuntimeError`` is
    folded into the skip branch for the same reason as
    :func:`_query_speakers`.
    """
    sc = _try_import_soundcard()
    if sc is None:
        return None
    try:
        return list(
            sc.all_microphones(  # pyright: ignore[reportUnknownMemberType]
                include_loopback=True
            )
        )
    except (OSError, RuntimeError) as exc:
        _helpers.log(f"sc.all_microphones() failed: {exc!r}")
        return None


def _resolve_speaker(*, name: str) -> Any | None:
    """Return the soundcard ``Speaker`` matching *name*, or ``None``.

    Delegates to :func:`soundcard.get_speaker` so id-only matches (e.g.
    PulseAudio sink name ``"VRCPilotMic"`` vs description-derived
    ``Speaker.name="VRCPilot_Virtual_Mic"``) work too. Mirrors
    :func:`vrcpilot.mic.devices.lookup_speaker` so the scenario picks
    the same handle the library would.
    """
    sc = _try_import_soundcard()
    if sc is None:
        return None
    try:
        return sc.get_speaker(name)  # pyright: ignore[reportUnknownMemberType]
    except LookupError:
        return None


def _resolve_microphone(*, name: str) -> Any | None:
    """Return the soundcard ``Microphone`` matching *name*, or ``None``.

    Companion to :func:`_resolve_speaker` for the recording side of the
    loopback. ``include_loopback=True`` widens the search to PulseAudio
    monitor sources so ``VRCPilotMic.monitor`` is reachable; the match
    is performed by :func:`soundcard.get_microphone` (id + name with
    fuzzy fallback).
    """
    sc = _try_import_soundcard()
    if sc is None:
        return None
    try:
        return sc.get_microphone(  # pyright: ignore[reportUnknownMemberType]
            name, include_loopback=True
        )
    except LookupError:
        return None


def _resolve_device_names() -> tuple[str, str] | str:
    """Pick the playback / record substrings for this host.

    Returns either ``(playback, record)`` on success **or** a
    skip-reason string when the host lacks the prerequisites
    (unsupported platform, Linux setup not run, no derivable loopback
    pair). The caller distinguishes the two cases via
    :func:`isinstance` -- the string carries enough context for the
    scenario to print a ``PASS: mic (skipped: ...)`` line. Substrings
    come from environment overrides first and OS defaults second.
    """
    from vrcpilot.mic import VIRTUAL_MIC_SINK_NAME, default_device_name

    env_playback = os.environ.get("VRCPILOT_MIC_DEVICE")
    if env_playback:
        playback = env_playback
    else:
        default = default_device_name()
        if default is None:
            return f"no default mic device for platform {sys.platform!r}"
        playback = default

    # Linux pre-flight: the default substring (VIRTUAL_MIC_SINK_NAME) only
    # resolves after the null-sink has been registered. Import lazily so
    # non-Linux hosts never touch vrcpilot.mic.linux (its top-level raises
    # off-Linux).
    if sys.platform == "linux" and playback == VIRTUAL_MIC_SINK_NAME:
        from vrcpilot.mic.linux import is_registered

        if not is_registered():
            return (
                f"{VIRTUAL_MIC_SINK_NAME} not registered "
                "(run 'vrcpilot linux-mic register')"
            )

    env_record = os.environ.get(_LOOPBACK_DEVICE_ENV_VAR)
    if env_record:
        record = env_record
    else:
        derived = _default_loopback_record().get(playback)
        if derived is None:
            return (
                f"no default loopback record substring for playback "
                f"{playback!r} (set ${_LOOPBACK_DEVICE_ENV_VAR})"
            )
        record = derived

    return (playback, record)


def _sine_chunks() -> Iterator[NDArray[np.float32]]:
    """Yield 100 ms stereo chunks of a 440 Hz sine, total 1 s.

    Phase is continuous across chunk boundaries so the playback stream
    sees a clean tone rather than a phase-discontinuity click train,
    which would smear the cross-correlation peak.
    """
    total_frames = int(_TONE_SECONDS * _SAMPLE_RATE)
    chunk_frames = int(_CHUNK_SECONDS * _SAMPLE_RATE)
    t = np.arange(total_frames, dtype=np.float32) / _SAMPLE_RATE
    mono = (_SINE_AMPLITUDE * np.sin(2.0 * np.pi * _FREQUENCY_HZ * t)).astype(
        np.float32
    )
    stereo = np.stack([mono, mono], axis=1)
    for start in range(0, total_frames, chunk_frames):
        yield stereo[start : start + chunk_frames].copy()


class _LoopbackRecorder:
    """Background-thread pull-mode pump for a soundcard ``Microphone``.

    ``soundcard``'s recorder API is pull-mode: there is no callback,
    just a ``record(numframes)`` method that blocks until ``numframes``
    samples are available. We run that call inside a worker thread so
    the main thread is free to drive playback; the worker exits when
    ``_stop_event`` is set. The first observed chunk also sets
    ``_ready`` so the main thread can wait for the recorder to actually
    be capturing before it starts playing.

    Concurrency: ``self._chunks`` is appended only on the worker and
    only read after :meth:`__exit__` has joined it, so no lock is
    required.
    """

    def __init__(self, microphone: Any) -> None:
        self._microphone = microphone
        self._chunks: list[NDArray[np.float32]] = []
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_exc: Exception | None = None

    def __enter__(self) -> _LoopbackRecorder:
        self._thread = threading.Thread(
            target=self._run, name="mic-e2e-recorder", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            # Generous join: one ``record()`` call returns within a
            # block (10 ms here), but allow plenty of slack for slow
            # libpulse shutdown paths before we'd start to suspect a
            # hang.
            thread.join(timeout=5.0)
            self._thread = None
        if self._thread_exc is not None:
            raise self._thread_exc

    def _run(self) -> None:
        """Worker entry point: open the recorder and pump until stop."""
        try:
            recorder_cm = self._microphone.recorder(  # pyright: ignore[reportUnknownMemberType]
                samplerate=_SAMPLE_RATE,
                channels=_CHANNELS,
                blocksize=_RECORDER_BLOCKSIZE,
            )
            with recorder_cm as rec:
                while not self._stop_event.is_set():
                    chunk = rec.record(  # pyright: ignore[reportUnknownMemberType]
                        numframes=_RECORDER_BLOCKSIZE
                    )
                    # ``record`` returns float32 ndarray of shape
                    # (numframes, channels). Defensive cast keeps the
                    # downstream FFT happy if a backend ever hands back
                    # float64.
                    arr = np.asarray(chunk, dtype=np.float32)
                    self._chunks.append(arr)
                    if not self._ready.is_set():
                        self._ready.set()
        except Exception as exc:
            # Surface the failure to the main thread via __exit__ so
            # the scenario can FAIL rather than silently producing an
            # empty buffer. Also flip ``_ready`` so the main thread
            # doesn't deadlock waiting for a recorder that already
            # crashed. ``Exception`` (not ``BaseException``) so that
            # ``KeyboardInterrupt`` / ``SystemExit`` still propagate
            # naturally; soundcard surfaces backend errors as
            # ``RuntimeError`` / ``OSError`` which are both under
            # ``Exception``.
            self._thread_exc = exc
            self._ready.set()

    def wait_until_ready(self, timeout: float = 2.0) -> bool:
        """Block until the first ``record()`` call returns or *timeout*
        elapses."""
        return self._ready.wait(timeout=timeout)

    def collected(self) -> NDArray[np.float32]:
        """Concatenate every captured chunk into a single ``(N, 2)`` array."""
        if not self._chunks:
            return np.zeros((0, _CHANNELS), dtype=np.float32)
        return np.concatenate(self._chunks, axis=0)


def _verify_loopback(recording: NDArray[np.float32]) -> None:
    """Assert the recording carries the played sine, not pure silence.

    Two checks: an RMS floor (rules out the virtual mic being muted /
    wrong device) and an FFT-peak match against 440 Hz (rules out the
    signal arriving as noise or as content from an unrelated source).
    Both are deliberately lenient on this first pass; tighter latency /
    amplitude bounds wait for real-hardware calibration.
    """
    n_frames = int(recording.shape[0])
    assert n_frames > 0, "recording buffer is empty (recorder produced no data)"

    # Mix to mono for the level + spectral checks. Both loopback
    # channels carry the same sine so an unweighted mean is fine.
    mono = recording.mean(axis=1).astype(np.float32)
    rms = float(np.sqrt(np.mean(mono * mono)))
    _helpers.log(
        f"recording: frames={n_frames} duration={n_frames / _SAMPLE_RATE:.2f}s "
        f"rms={rms:.4f}"
    )
    assert rms > _RMS_SILENCE_FLOOR, (
        f"recording RMS {rms:.4f} below silence floor "
        f"{_RMS_SILENCE_FLOOR:.4f}; virtual mic likely muted or wrong device"
    )

    # Real-input FFT magnitudes: bin ``k`` corresponds to frequency
    # ``k * sample_rate / N`` Hz. With >1 s of audio at 48 kHz the bin
    # width is well under 1 Hz, so the 440 Hz tone lands in a tightly
    # localised peak.
    spectrum = np.abs(np.fft.rfft(mono))
    bin_hz = _SAMPLE_RATE / mono.shape[0]
    expected_bin = int(round(_FREQUENCY_HZ / bin_hz))
    peak_bin = int(np.argmax(spectrum))
    peak_hz = peak_bin * bin_hz
    _helpers.log(
        f"spectrum: peak_bin={peak_bin} ({peak_hz:.1f} Hz) "
        f"expected_bin={expected_bin} ({_FREQUENCY_HZ:.1f} Hz) "
        f"bin_width={bin_hz:.3f} Hz"
    )
    assert abs(peak_bin - expected_bin) <= _FREQUENCY_BIN_TOLERANCE, (
        f"loudest FFT bin {peak_bin} ({peak_hz:.1f} Hz) is more than "
        f"{_FREQUENCY_BIN_TOLERANCE} bins from the played tone "
        f"({_FREQUENCY_HZ:.1f} Hz); signal does not look like the sine"
    )


def _scenario() -> str | None:
    """Run the loopback. Returns a "skipped" reason string, or ``None`` on
    success.

    Raises on any verification failure; :func:`main` converts the
    exception into a ``FAIL:`` line.
    """
    speakers = _query_speakers()
    if speakers is None:
        return "soundcard not installed (or libpulse missing)"
    mics = _query_microphones()
    if mics is None:
        return "soundcard not installed (or libpulse missing)"

    resolved = _resolve_device_names()
    if isinstance(resolved, str):
        return resolved
    # Narrow for pyright + readers: post-isinstance the tuple branch is
    # the only remaining option, so spell it out before destructuring.
    assert not isinstance(resolved, str)
    playback_name, record_name = resolved

    playback_speaker = _resolve_speaker(name=playback_name)
    record_mic = _resolve_microphone(name=record_name)
    if playback_speaker is None or record_mic is None:
        missing = playback_name if playback_speaker is None else record_name
        playback_id = (
            getattr(playback_speaker, "id", None)
            if playback_speaker is not None
            else None
        )
        record_id = getattr(record_mic, "id", None) if record_mic is not None else None
        speaker_listing = ", ".join(
            f"{getattr(sp, 'name', '?')!r}(id={getattr(sp, 'id', '?')!r})"
            for sp in speakers
        )
        mic_listing = ", ".join(
            f"{getattr(m, 'name', '?')!r}(id={getattr(m, 'id', '?')!r})" for m in mics
        )
        _helpers.log(
            f"loopback halves not found: "
            f"{playback_name!r} (speaker) -> id={playback_id!r}, "
            f"{record_name!r} (microphone) -> id={record_id!r}"
        )
        _helpers.log(f"available speakers: {speaker_listing or '(none)'}")
        _helpers.log(f"available microphones: {mic_listing or '(none)'}")
        return (
            f"loopback device {missing!r} not found "
            f"(set $VRCPILOT_MIC_DEVICE / ${_LOOPBACK_DEVICE_ENV_VAR})"
        )

    _helpers.log(
        f"loopback: playback={playback_name!r} "
        f"(id={getattr(playback_speaker, 'id', None)!r}) "
        f"record={record_name!r} "
        f"(id={getattr(record_mic, 'id', None)!r})"
    )

    # Import here so the skip branches above can run even on hosts
    # without soundcard (the import inside Mic uses the same lazy path,
    # but we want to be explicit about ordering here).
    from vrcpilot.mic import Mic

    with _LoopbackRecorder(record_mic) as recorder:
        if not recorder.wait_until_ready(timeout=2.0):
            raise RuntimeError("recorder first chunk did not arrive within 2s")
        # Extra lead-in beyond first-chunk-ready ensures we have a
        # margin of recorded zeros before the tone arrives.
        time.sleep(_RECORD_LEAD_IN_SECONDS)
        _helpers.log(f"playing {_TONE_SECONDS:.2f}s of {_FREQUENCY_HZ:.0f} Hz sine")
        with Mic(
            playback_name,
            sample_rate=_SAMPLE_RATE,
            channels=_CHANNELS,
        ) as mic:
            for chunk in _sine_chunks():
                mic.play(chunk)
        # Trail-out so the recorder captures any tail latency.
        time.sleep(_RECORD_TAIL_SECONDS)
        recording = recorder.collected()

    _verify_loopback(recording)
    return None


def main() -> int:
    _helpers.log("=== scenario: mic ===")
    try:
        skipped = _scenario()
    except Exception as exc:
        _helpers.log(f"scenario raised: {exc!r}")
        print(f"FAIL: mic: {exc}", flush=True)
        return 1
    if skipped is not None:
        print(f"PASS: mic (skipped: {skipped})", flush=True)
    else:
        print("PASS: mic", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
