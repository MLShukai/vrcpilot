"""E2E scenario: cross-platform Mic loopback verification.

Plays a sine through :class:`vrcpilot.mic.Mic` (real :mod:`soundcard`
backend: libpulse on Linux, WASAPI on Windows) and asserts the same
tone re-emerges on the matching loopback recording device. Windows
loops ``CABLE Input`` -> ``CABLE Output`` (VB-Cable); Linux loops the
``VRCPilotMic`` null-sink to its monitor source.

Unlike every other scenario here this one does **not** launch VRChat:
the test exercises only the mic output path
(Python -> soundcard -> virtual mic -> soundcard input). ``vrcpilot
record`` (proc-tap, process-loopback) is intentionally unused -- that
is a different code path.

Run with ``just e2e-test mic``. Skip semantics: any missing
prerequisite (no soundcard, no libpulse, no matching device pair, no
Linux registration) produces ``PASS: mic (skipped: ...)`` rather than
failure, mirroring how unit tests use ``pytest.skip`` for platform-only
deps.

Env vars (loaded automatically by ``just e2e-test`` via dotenv):

* ``$VRCPILOT_MIC_DEVICE`` -- override the playback substring. Also
  honoured by :class:`vrcpilot.mic.Mic` itself.
* ``$VRCPILOT_MIC_LOOPBACK_DEVICE`` -- override the record substring.
  E2E-only; the library does not read it.

Verification is intentionally lenient on this first pass: RMS clears
an obvious-silence floor and the FFT peak lands within
:data:`_FREQUENCY_BIN_TOLERANCE` bins of 440 Hz. Tighter
latency / amplitude bounds wait for real-hardware calibration.

Prerequisites (host-dependent):

* Windows: VB-Audio Virtual Cable installed
  (https://vb-audio.com/Cable/) so ``CABLE Input`` / ``CABLE Output``
  show up under WASAPI.
* Linux: ``vrcpilot linux-mic register`` has been run and libpulse is
  available so :mod:`soundcard` can talk to PipeWire-pulse.
* ``soundcard`` installed in the active uv environment (project-wide
  dependency, covered by ``uv sync``).
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
    """Map default-playback substring -> matching default-record substring.

    Linux entry uses ``VIRTUAL_MIC_SINK_NAME`` from the library plus the
    explicit ``.monitor`` suffix the null-sink convention exposes;
    ``soundcard.get_microphone`` does an exact-id lookup before falling
    back to a fuzzy name scan, so the bare sink name does not match.

    Built lazily inside a function so the ``vrcpilot.mic`` import is
    deferred until :func:`main` runs (collection still works on hosts
    where the package's module-level state fails to construct).
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

    Folds "soundcard not installed" (``ImportError``) and "libpulse not
    loadable" (``OSError`` -- soundcard raises this when the native
    backend cannot be dlopened) into the same skip branch in
    :func:`_scenario` so the four callsites do not duplicate the
    try/except.
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
    """Return ``sc.all_speakers()`` or ``None`` to trigger the skip branch.

    ``None`` also when enumeration itself raises ``RuntimeError`` --
    some libpulse builds dlopen lazily on first enumeration so the
    failure surfaces here rather than at import time.
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
    """Return ``sc.all_microphones(include_loopback=True)`` or ``None``.

    ``include_loopback=True`` is load-bearing: PulseAudio monitor
    sources (e.g. ``VRCPilotMic.monitor``) are filtered out of the
    default view, which made the Linux loopback scenario find nothing
    earlier. ``RuntimeError`` folds into the skip branch like
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
    """Return the soundcard ``Speaker`` matching ``name`` or ``None``.

    Delegates to :func:`soundcard.get_speaker` -- the same call
    :func:`vrcpilot.mic.devices.lookup_speaker` uses -- so the scenario
    picks exactly the handle the library would, including via the
    id-only ``VRCPilotMic`` / ``VRCPilot_Virtual_Mic`` divergence.
    """
    sc = _try_import_soundcard()
    if sc is None:
        return None
    try:
        return sc.get_speaker(name)  # pyright: ignore[reportUnknownMemberType]
    except LookupError:
        return None


def _resolve_microphone(*, name: str) -> Any | None:
    """Return the soundcard ``Microphone`` matching ``name`` or ``None``.

    Companion to :func:`_resolve_speaker` for the record side.
    ``include_loopback=True`` widens the search to PulseAudio monitor
    sources so ``VRCPilotMic.monitor`` is reachable.
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

    Returns ``(playback, record)`` on success, or a skip-reason string
    when the host lacks a prerequisite (unsupported platform, Linux
    setup not run, no derivable loopback pair). The caller distinguishes
    via :func:`isinstance` and prints the string as the
    ``PASS: mic (skipped: ...)`` reason. Substrings come from env
    overrides first, OS defaults second.
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
    sees a clean tone -- a phase-discontinuity click train would smear
    the FFT peak.
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

    ``soundcard``'s recorder API is pull-mode (no callback, just
    blocking ``record(numframes)``), so the call runs on a worker
    thread while the main thread drives playback. The worker exits on
    ``_stop_event``; ``_ready`` flips on the first observed chunk so
    the main thread can wait for actual capture before starting to
    play.

    Concurrency: ``self._chunks`` is appended only by the worker and
    only read after :meth:`__exit__` joins it, so no lock is needed.
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
            # One ``record()`` returns within ~10 ms, but allow ample
            # slack for slow libpulse shutdown paths before suspecting
            # a hang.
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
                    # Defensive cast: ``record`` returns float32 but
                    # some backends have been observed to hand back
                    # float64, which trips the downstream FFT path.
                    arr = np.asarray(chunk, dtype=np.float32)
                    self._chunks.append(arr)
                    if not self._ready.is_set():
                        self._ready.set()
        except Exception as exc:
            # Surface the failure to the main thread via __exit__ so
            # the scenario FAILs rather than silently producing an
            # empty buffer. Set ``_ready`` so the main thread does not
            # deadlock waiting on a recorder that already crashed.
            # Catch ``Exception`` (not ``BaseException``) so
            # ``KeyboardInterrupt`` / ``SystemExit`` still propagate;
            # soundcard backend errors are ``RuntimeError`` / ``OSError``,
            # both under ``Exception``.
            self._thread_exc = exc
            self._ready.set()

    def wait_until_ready(self, timeout: float = 2.0) -> bool:
        """Block until the recorder has captured at least one chunk."""
        return self._ready.wait(timeout=timeout)

    def collected(self) -> NDArray[np.float32]:
        """Concatenate every captured chunk into a single ``(N, 2)`` array."""
        if not self._chunks:
            return np.zeros((0, _CHANNELS), dtype=np.float32)
        return np.concatenate(self._chunks, axis=0)


def _verify_loopback(recording: NDArray[np.float32]) -> None:
    """Assert the recording carries the played sine, not silence or noise.

    Two checks: an RMS floor (rules out the virtual mic being muted or
    the wrong device) and an FFT-peak match against 440 Hz (rules out
    the signal arriving as noise or content from an unrelated source).
    Both are deliberately lenient on the first pass; tighter
    latency / amplitude bounds wait for real-hardware calibration.
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
    """Run the loopback once.

    Returns a skip-reason string when a prerequisite is missing or
    ``None`` after a successful verification. Raises on any
    verification failure; :func:`main` converts the exception into a
    ``FAIL:`` line.
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
    """Scenario entry point invoked by ``just e2e-test mic``."""
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
