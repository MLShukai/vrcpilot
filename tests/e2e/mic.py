"""E2E scenario: cross-platform Mic loopback verification.

Drives :class:`vrcpilot.mic.Mic` against the real PortAudio backend and
confirms that audio written to the platform's virtual mic device re-emerges
on the matching loopback recording device. On Windows this resolves to
VB-Audio Virtual Cable (``CABLE Input`` -> ``CABLE Output``); on Linux it
resolves to the PipeWire ``VRCPilotMic`` null-sink registered by
``vrcpilot linux-mic register`` (whose ``Monitor of VRCPilot Virtual Mic``
source matches the same ``VRCPilotMic`` substring).

Unlike every other scenario in this directory, this one does **not** launch
VRChat: the test is about the mic-modality output path (Python ->
sounddevice -> virtual mic -> sounddevice input) and VRChat's own audio
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
* Probe :func:`sounddevice.query_devices` for both substrings. If either is
  missing the scenario PASSes with a "skipped" note, mirroring how the
  codebase handles platform-only deps in unit tests via ``pytest.skip``.
  The same applies if :mod:`sounddevice` itself is not installed, or if
  the Linux setup step (``vrcpilot linux-mic register``) has not been run.
* A background thread opens ``InputStream`` on the record device and
  appends every callback chunk to a list. The list is converted to a
  contiguous ndarray once the stream is closed, so no synchronisation
  primitive is needed during recording.
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
  show up under PortAudio.
* Linux: ``vrcpilot linux-mic register`` has been run so the
  ``VRCPilotMic`` PipeWire null-sink (plus its ``Monitor of VRCPilot
  Virtual Mic`` source) exists.
* ``sounddevice`` installed in the active uv environment (it is a
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
    :func:`vrcpilot.mic.default_device_name`. For Linux the same
    :data:`vrcpilot.mic.VIRTUAL_MIC_SINK_NAME` substring matches both
    the null-sink itself and its ``Monitor of VRCPilot Virtual Mic``
    source (PortAudio surfaces the monitor with ``VRCPilotMic`` in its
    name), so a single entry suffices. The Linux key is read from
    ``vrcpilot.mic.VIRTUAL_MIC_SINK_NAME`` so the e2e harness never
    drifts away from the production constant.

    Built lazily inside a function so the ``vrcpilot.mic`` import (and
    its OS-conditional sub-imports) is deferred until ``main()`` runs
    -- collection still works on hosts where the package fails to
    construct module-level state.
    """
    from vrcpilot.mic import VIRTUAL_MIC_SINK_NAME

    return {
        "CABLE Input": "CABLE Output",
        VIRTUAL_MIC_SINK_NAME: VIRTUAL_MIC_SINK_NAME,
    }


#: Sample rate / channel count for the loopback. 48 kHz matches the
#: project's pinned :data:`vrcpilot.mic.SAMPLE_RATE`. Stereo is passed
#: explicitly to ``Mic(..., channels=_CHANNELS)`` so the playback
#: stream opens in stereo at construction time.
_SAMPLE_RATE = 48000
_CHANNELS = 2

#: Sine tone parameters. 440 Hz (A4) is well within both VB-Cable's and
#: PipeWire's pass band and far from DC, so any high-pass on the path
#: leaves it intact.
_FREQUENCY_HZ = 440.0
_TONE_SECONDS = 1.0
_CHUNK_SECONDS = 0.1

#: Lead-in time the recorder gets before playback starts. Long enough
#: for the InputStream callback thread to spin up; short enough that
#: the head of the sine still lands inside the recording buffer.
_RECORD_LEAD_IN_SECONDS = 0.2

#: Trailing silence captured after playback ends so the cross-correlation
#: window covers the whole tone even if PortAudio adds a few hundred ms
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


def _query_devices() -> list[dict[str, Any]] | None:
    """Return PortAudio's device list, or ``None`` if sounddevice missing.

    Returning ``None`` (rather than re-raising) lets the caller treat
    the import failure the same as a missing virtual mic and produce a
    single "skipped" branch.
    """
    try:
        import sounddevice as sd  # pyright: ignore[reportMissingTypeStubs]
    except Exception as exc:
        _helpers.log(f"sounddevice import failed: {exc!r}")
        return None
    return list(sd.query_devices())  # pyright: ignore[reportUnknownMemberType]


def _resolve_device_index(
    devices: list[dict[str, Any]],
    *,
    name: str,
    direction: str,
) -> int | None:
    """Locate a device whose name contains *name*, returning its sounddevice
    index.

    ``direction`` selects ``max_output_channels`` (playback) or
    ``max_input_channels`` (recording) so we never pick the wrong
    half of a pair -- VB-Cable, for instance, exposes both names on
    each side and only one direction is usable per half.
    """
    field = "max_output_channels" if direction == "output" else "max_input_channels"
    needle = name.lower()
    for index, info in enumerate(devices):
        if int(info.get(field, 0)) <= 0:
            continue
        if needle in str(info.get("name", "")).lower():
            return index
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
    """Background-thread InputStream pump for the loopback record device.

    The PortAudio callback runs on its own thread; we only append the
    incoming buffer to a list there and defer concatenation until
    :meth:`stop` joins the stream. That keeps the callback short
    (PortAudio docs warn against blocking work) and avoids any locking
    around the growing buffer.
    """

    def __init__(self, device_index: int) -> None:
        self._device_index = device_index
        self._chunks: list[NDArray[np.float32]] = []
        self._stream: Any = None
        self._ready = threading.Event()

    def __enter__(self) -> _LoopbackRecorder:
        import sounddevice as sd  # pyright: ignore[reportMissingTypeStubs]

        def _callback(
            indata: NDArray[np.float32],
            _frames: int,
            _time: Any,
            _status: Any,
        ) -> None:
            # Copy: PortAudio reuses the underlying buffer for the next
            # tick, so a bare reference would alias future audio.
            self._chunks.append(indata.copy())
            if not self._ready.is_set():
                self._ready.set()

        self._stream = sd.InputStream(  # pyright: ignore[reportUnknownMemberType]
            device=self._device_index,
            channels=_CHANNELS,
            samplerate=_SAMPLE_RATE,
            dtype="float32",
            callback=_callback,
        )
        self._stream.start()  # pyright: ignore[reportUnknownMemberType]
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()  # pyright: ignore[reportUnknownMemberType]
            finally:
                self._stream.close()  # pyright: ignore[reportUnknownMemberType]
            self._stream = None

    def wait_until_ready(self, timeout: float = 2.0) -> bool:
        """Block until the first callback fires or *timeout* elapses."""
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
    assert n_frames > 0, "recording buffer is empty (InputStream produced no data)"

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
    devices = _query_devices()
    if devices is None:
        return "sounddevice not installed"

    resolved = _resolve_device_names()
    if isinstance(resolved, str):
        return resolved
    # Narrow for pyright + readers: post-isinstance the tuple branch is
    # the only remaining option, so spell it out before destructuring.
    assert not isinstance(resolved, str)
    playback_name, record_name = resolved

    playback_idx = _resolve_device_index(
        devices, name=playback_name, direction="output"
    )
    record_idx = _resolve_device_index(devices, name=record_name, direction="input")
    if playback_idx is None or record_idx is None:
        missing = playback_name if playback_idx is None else record_name
        _helpers.log(
            f"loopback halves not found: "
            f"{playback_name!r} (output) -> {playback_idx}, "
            f"{record_name!r} (input) -> {record_idx}"
        )
        return (
            f"loopback device {missing!r} not found "
            f"(set $VRCPILOT_MIC_DEVICE / ${_LOOPBACK_DEVICE_ENV_VAR})"
        )

    _helpers.log(
        f"loopback: playback={playback_name!r} (idx={playback_idx}) "
        f"record={record_name!r} (idx={record_idx})"
    )

    # Import here so the skip branches above can run even on hosts
    # without sounddevice (the import inside Mic uses the same lazy
    # path, but we want to be explicit about ordering here).
    from vrcpilot.mic import Mic

    with _LoopbackRecorder(record_idx) as recorder:
        if not recorder.wait_until_ready(timeout=2.0):
            raise RuntimeError("InputStream first callback did not fire within 2s")
        # Extra lead-in beyond first-callback ensures we have a margin
        # of recorded zeros before the tone arrives.
        time.sleep(_RECORD_LEAD_IN_SECONDS)
        _helpers.log(f"playing {_TONE_SECONDS:.2f}s of {_FREQUENCY_HZ:.0f} Hz sine")
        with Mic(
            playback_name,
            sample_rate=_SAMPLE_RATE,
            channels=_CHANNELS,
        ) as mic:
            for chunk in _sine_chunks():
                mic.play(chunk)
        # Trail-out so the InputStream captures any tail latency.
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
