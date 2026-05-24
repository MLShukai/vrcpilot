"""Integration-real tests for :class:`vrcpilot.mic.Mic` on Linux.

Spawns a transient PipeWire / PulseAudio null-sink via ``pactl
load-module`` so the test exercises the **real** :mod:`soundcard`
player wired into a real sink. The sink is unloaded in fixture
teardown so the system audio graph is left untouched between tests.

Why not patch :mod:`soundcard`: the testing skill bans mirroring
3rd-party surfaces. Driving the real library against a transient sink
catches drift that a fake never would (PipeWire / soundcard upgrades,
device-id rewriting between PulseAudio versions, etc.).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterator

import numpy as np
import pytest

if not sys.platform.startswith("linux"):
    pytest.skip("Linux-only Mic integration tests", allow_module_level=True)

# soundcard reads sys.argv[1] at import time on Linux; make sure that
# attribute exists before any test triggers the lazy import inside
# ``Mic`` / ``lookup_speaker``.
sys.argv = sys.argv or ["pytest"]
if len(sys.argv) < 2:
    sys.argv.append("pytest-placeholder")

try:
    import soundcard as _sc  # type: ignore[import-not-found]  # noqa: E402,F401
except Exception as _exc:  # noqa: BLE001
    pytest.skip(
        f"soundcard unavailable on this Linux host: {_exc}",
        allow_module_level=True,
    )

if shutil.which("pactl") is None:
    pytest.skip(
        "pactl is required to spawn a transient null-sink", allow_module_level=True
    )

# Quick liveness check: a host without a running PulseAudio / PipeWire
# server has pactl installed but ``pactl info`` returns non-zero. Skip
# rather than time out per-test.
_probe = subprocess.run(["pactl", "info"], capture_output=True, text=True)
if _probe.returncode != 0:
    pytest.skip(
        f"no PulseAudio/PipeWire server reachable: {_probe.stderr.strip()}",
        allow_module_level=True,
    )

from vrcpilot.mic import Mic, MicDeviceNotFoundError  # noqa: E402
from vrcpilot.mic.base import DEVICE_ENV_VAR  # noqa: E402

_TEST_SINK = "vrcpilot_session_test_sink"


@pytest.fixture
def transient_null_sink() -> Iterator[str]:
    """Spawn a real ``module-null-sink`` and tear it down on exit.

    Yields the sink's PulseAudio-side name so tests can pass it as
    ``--device`` / construct :class:`Mic` against it. Uses ``pactl
    load-module`` (the PulseAudio compatibility layer) which PipeWire
    accepts natively, mirroring how the real
    :func:`vrcpilot.mic.linux.register_virtual_mic` runtime path
    works.
    """
    proc = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={_TEST_SINK}",
            f"sink_properties=device.description={_TEST_SINK}",
            "rate=48000",
            "channels=1",
            "format=float32le",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(
            f"pactl load-module failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    module_id = proc.stdout.strip()
    try:
        yield _TEST_SINK
    finally:
        subprocess.run(
            ["pactl", "unload-module", module_id],
            capture_output=True,
            text=True,
        )


class TestMicAgainstRealNullSink:
    def test_opens_against_explicit_device(self, transient_null_sink: str) -> None:
        # The whole point of the explicit-device path: the user names a
        # sink they registered themselves and Mic binds to it. The
        # device_name we report back must reflect what the caller asked
        # for, and device_id must come from soundcard's view of the
        # backing sink.
        with Mic(transient_null_sink, channels=1) as mic:
            assert mic.device_name == transient_null_sink
            # PulseAudio surfaces null-sinks with id == sink_name.
            assert transient_null_sink in mic.device_id
            assert mic.sample_rate == 48000
            assert mic.channels == 1

    def test_play_streams_chunks_without_error(self, transient_null_sink: str) -> None:
        # ``play`` is the hot path: it must accept a float32 mono chunk
        # and return without raising. The null-sink consumes the data
        # silently; we only verify that the API call shape works
        # end-to-end against the real soundcard player.
        with Mic(transient_null_sink, channels=1) as mic:
            chunk = np.zeros(480, dtype=np.float32)  # 10ms at 48kHz
            mic.play(chunk)

    def test_play_after_close_raises_runtime_error(
        self, transient_null_sink: str
    ) -> None:
        # Lifecycle contract: post-close play is a misuse and must
        # surface as RuntimeError, not e.g. a libpulse segfault.
        mic = Mic(transient_null_sink, channels=1)
        mic.close()
        with pytest.raises(RuntimeError, match="closed"):
            mic.play(np.zeros(10, dtype=np.float32))

    def test_close_is_idempotent(self, transient_null_sink: str) -> None:
        # close() must be safe to call repeatedly; the wrapper is the
        # only level where idempotency is guaranteed (the underlying
        # soundcard CM would raise on double-exit).
        mic = Mic(transient_null_sink, channels=1)
        mic.close()
        mic.close()
        mic.close()

    def test_context_manager_closes(self, transient_null_sink: str) -> None:
        # The __enter__ / __exit__ wiring must release the underlying
        # soundcard player on exit; after the with-block, follow-up
        # play() is forbidden.
        with Mic(transient_null_sink, channels=1) as mic:
            pass
        with pytest.raises(RuntimeError, match="closed"):
            mic.play(np.zeros(10, dtype=np.float32))

    def test_resolves_default_device_via_env_var(
        self,
        transient_null_sink: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The env-var path is documented as the second-priority
        # resolution source (after the explicit argument). Pointing
        # $VRCPILOT_MIC_DEVICE at our transient sink and constructing
        # Mic() with no argument must bind to that sink.
        monkeypatch.setenv(DEVICE_ENV_VAR, transient_null_sink)
        with Mic() as mic:
            assert mic.device_name == transient_null_sink


class TestMicNoMatchingDevice:
    def test_lookup_failure_surfaces_as_mic_device_not_found(
        self,
    ) -> None:
        # A bogus device substring must surface as the typed exception
        # (so CLI / callers can catch it cleanly) rather than leaking
        # soundcard's untyped LookupError.
        with pytest.raises(MicDeviceNotFoundError):
            Mic("vrcpilot-no-such-device-zzz-marker", channels=1)


class TestChunkValidation:
    def test_channel_mismatch_rejected(self, transient_null_sink: str) -> None:
        # The validation message must mention "channel" so the caller
        # can diagnose the mismatch from the exception alone. We open
        # a 1-channel Mic and try to feed it a stereo chunk -- a clear
        # caller bug that the wrapper must reject before forwarding to
        # soundcard (which would silently mis-interpret the data).
        with Mic(transient_null_sink, channels=1) as mic:
            with pytest.raises(ValueError, match="channel"):
                mic.play(np.zeros((10, 2), dtype=np.float32))

    def test_non_float32_chunk_rejected(self, transient_null_sink: str) -> None:
        # dtype enforcement must catch int16 / float64 etc. before
        # forwarding to the soundcard player (which would silently
        # mis-interpret bytes).
        with Mic(transient_null_sink, channels=1) as mic:
            with pytest.raises(ValueError, match="float32"):
                mic.play(np.zeros(10, dtype=np.int16))

    def test_three_dim_chunk_rejected(self, transient_null_sink: str) -> None:
        # Only (N,) or (N, C) shapes are documented; (N, C, X) must
        # surface as a ValueError pointing at the dimensionality.
        with Mic(transient_null_sink, channels=1) as mic:
            with pytest.raises(ValueError, match="1-D"):
                mic.play(np.zeros((10, 1, 1), dtype=np.float32))
