"""Integration-real tests for :mod:`vrcpilot.speaker.proctap`.

These tests drive the *real* proc-tap backend against a running VRChat
process. Unlike :mod:`tests.vrcpilot.speaker.test_proctap` they perform
no factory substitution -- the only purpose here is to catch
regressions the fakes cannot see (proc-tap initialisation, real packet
shapes, lifecycle on a live device).

Run requirements (any unmet condition causes a test-level
``pytest.skip``):

* VRChat is running. The autouse ``_no_real_vrchat`` fixture in
  :mod:`tests.conftest` forces ``find_pid`` to return ``None`` by
  patching ``psutil.process_iter``; each test undoes that patch via
  ``monkeypatch.undo`` so the live process can be observed.
* Host OS has a proc-tap native backend (Windows/Linux are stable;
  macOS is experimental). Import failures from proc-tap surface as a
  test failure rather than a silent skip so an environment regression
  is loud.

The tests assert only the public contract (dtype, shape, channel
count, idempotent close). They deliberately do not assert anything
about signal level - VRChat's default world is often silent and the
goal here is plumbing, not audio quality.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from vrcpilot import process
from vrcpilot.speaker.base import CHANNELS, SAMPLE_RATE
from vrcpilot.speaker.proctap import ProcTapSpeakerBackend


@pytest.fixture
def real_vrchat(monkeypatch: pytest.MonkeyPatch) -> int:
    """Skip unless a live VRChat process can be observed.

    Undoes the autouse ``_no_real_vrchat`` ``psutil.process_iter``
    patch so :func:`vrcpilot.process.find_pid` queries the real OS,
    then skips the test if no VRChat is present. Returns the live
    PID for tests that want to log it.
    """
    monkeypatch.undo()
    pid = process.find_pid()
    if pid is None:
        pytest.skip("VRChat is not running; cannot exercise proc-tap process loopback")
    return pid


def _drain_until_signal(
    backend: ProcTapSpeakerBackend,
    *,
    max_seconds: float,
) -> np.ndarray:
    """Pull from *backend* up to *max_seconds*, returning the first non-empty
    chunk.

    VRChat may be silent at start-up (no avatar audio, no world music
    yet). ``ProcTapSpeakerBackend.read`` returns ``(0, CHANNELS)`` on
    a silent tick, so a single read is not enough to verify the
    *shape* of a populated packet. We keep reading until either a real
    packet arrives or the budget is exhausted; on exhaustion the
    contract still holds (dtype/shape/channel count of the empty
    chunk), so the caller can fall back to that.
    """
    deadline = time.monotonic() + max_seconds
    last_chunk = backend.read()
    while last_chunk.shape[0] == 0 and time.monotonic() < deadline:
        last_chunk = backend.read()
    return last_chunk


class TestRealProcTapBackend:
    """Live proc-tap backend against the real VRChat process."""

    def test_constructs_against_live_vrchat(self, real_vrchat: int):
        backend = ProcTapSpeakerBackend()
        try:
            assert backend is not None
        finally:
            backend.close()
        # The PID is informational; failing to look it up earlier in
        # the fixture is what actually skips the test.
        del real_vrchat

    def test_read_returns_float32_stereo(self, real_vrchat: int):
        del real_vrchat
        backend = ProcTapSpeakerBackend(read_timeout=1.0)
        try:
            chunk = _drain_until_signal(backend, max_seconds=2.0)
        finally:
            backend.close()

        assert chunk.dtype == np.float32
        assert chunk.ndim == 2
        assert chunk.shape[1] == CHANNELS

    def test_one_second_window_yields_reasonable_sample_count(self, real_vrchat: int):
        """Roughly 1 s of reads should expose at least one real packet.

        We do not assert ``len == SAMPLE_RATE`` because proc-tap
        delivers in 10-20 ms chunks and the loop boundary will straddle
        the wall-clock window. The looser claim - that every read is
        well-formed and the cumulative count never exceeds the device
        clock - is what the contract actually promises.
        """
        del real_vrchat
        backend = ProcTapSpeakerBackend(read_timeout=0.2)
        total_samples = 0
        try:
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                chunk = backend.read()
                # Every read, populated or not, must honour the
                # contract.
                assert chunk.dtype == np.float32
                assert chunk.ndim == 2
                assert chunk.shape[1] == CHANNELS
                total_samples += int(chunk.shape[0])
        finally:
            backend.close()

        # ``total_samples == 0`` is technically allowed if VRChat is
        # completely silent for the full second, so we only assert
        # the rate bound when something arrived.
        if total_samples > 0:
            # Sanity: the rate must not exceed the device sample rate
            # by more than a small factor. proc-tap never delivers
            # *more* samples than the device clock implies; if this
            # trips, the buffer accounting is wrong.
            assert total_samples <= SAMPLE_RATE * 2

    def test_close_is_idempotent(self, real_vrchat: int):
        del real_vrchat
        backend = ProcTapSpeakerBackend()
        backend.close()
        # A second close must not raise; the wrapper and proc-tap
        # session both guard against it but only a live session
        # exercises every branch.
        backend.close()
