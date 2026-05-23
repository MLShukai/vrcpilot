"""Tests for :mod:`vrcpilot.speaker.windows`.

The backend talks to :mod:`proctap` only via its ``_open_capture``
factory; tests patch that factory with a duck-typed
:class:`tests.fakes.FakeProcessAudioCapture` so we never need a real
WASAPI device to exercise the read / close plumbing.

The backend now takes ``pid`` as a required keyword (PID resolution
lives in :class:`vrcpilot.speaker.Speaker`); the helper :func:`patch_pid`
provides the canonical deterministic PID for tests.
"""

from __future__ import annotations

import sys

import pytest

# vrcpilot.speaker.windows raises ImportError on non-Windows hosts
# (proc-tap is Windows-only-installed), so skip before the production
# import below would crash pytest collection on Linux CI.
if sys.platform != "win32":
    pytest.skip(
        "vrcpilot.speaker.windows is Windows-only",
        allow_module_level=True,
    )

import logging

import numpy as np
from pytest_mock import MockerFixture

from tests.fakes import FakeProcessAudioCapture
from vrcpilot.speaker.base import CHANNELS
from vrcpilot.speaker.windows import ProcTapSpeakerBackend


@pytest.fixture
def patch_pid() -> int:
    """Return the deterministic PID used by the rest of the test fixtures.

    PID resolution moved out of the backend and into
    :class:`vrcpilot.speaker.Speaker`; the backend now takes ``pid`` as
    a required keyword, so this fixture is just a constant.
    """
    return 4242


@pytest.fixture
def backend_and_capture(
    mocker: MockerFixture,
    patch_pid: int,
) -> tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture]:
    """Build a backend whose ``_open_capture`` returns a fake.

    Yields the ``(backend, fake_capture)`` pair so individual tests can
    queue PCM bytes on the fake and then drain via ``backend.read()``.
    """
    fake = FakeProcessAudioCapture(pid=patch_pid)
    mocker.patch.object(ProcTapSpeakerBackend, "_open_capture", return_value=fake)
    return ProcTapSpeakerBackend(pid=patch_pid), fake


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    @pytest.mark.parametrize("bad", [0.0, -0.5, -1.0])
    def test_rejects_non_positive_read_timeout(
        self,
        mocker: MockerFixture,
        bad: float,
        patch_pid: int,
    ):
        # Validation must fire before the capture is constructed so a
        # misuse never reaches proc-tap.
        spy = mocker.patch.object(
            ProcTapSpeakerBackend,
            "_open_capture",
            return_value=FakeProcessAudioCapture(pid=patch_pid),
        )
        with pytest.raises(ValueError, match="read_timeout must be > 0"):
            ProcTapSpeakerBackend(read_timeout=bad, pid=patch_pid)
        spy.assert_not_called()

    def test_starts_capture_on_construction(
        self,
        backend_and_capture: tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture],
    ):
        # The proc-tap stream must be started before the first read,
        # otherwise read() returns None forever.
        backend, fake = backend_and_capture
        try:
            assert fake.start_calls == 1
        finally:
            backend.close()

    def test_forwards_pid_to_open_capture(
        self,
        mocker: MockerFixture,
        patch_pid: int,
    ):
        # _open_capture is the one place the PID hands off to proc-tap;
        # if the kwarg is missing the wrong process is captured.
        spy = mocker.patch.object(
            ProcTapSpeakerBackend,
            "_open_capture",
            return_value=FakeProcessAudioCapture(pid=patch_pid),
        )
        backend = ProcTapSpeakerBackend(pid=patch_pid)
        try:
            spy.assert_called_once()
            assert spy.call_args.kwargs == {"pid": patch_pid}
        finally:
            backend.close()

    def test_uses_explicit_pid(
        self,
        mocker: MockerFixture,
    ):
        # The backend's whole purpose under the C6 refactor is to take
        # the caller's pid verbatim — no resolve_pid / find_pid lookups.
        # Confirm a non-default PID flows through unmodified.
        explicit = 9999
        spy = mocker.patch.object(
            ProcTapSpeakerBackend,
            "_open_capture",
            return_value=FakeProcessAudioCapture(pid=explicit),
        )
        backend = ProcTapSpeakerBackend(pid=explicit)
        try:
            assert spy.call_args.kwargs == {"pid": explicit}
        finally:
            backend.close()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class TestRead:
    def test_returns_empty_array_when_queue_drained(
        self,
        backend_and_capture: tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture],
    ):
        # proc-tap returns None on a timeout; the backend must surface
        # that as an empty (0, CHANNELS) ndarray so consumers can poll
        # without exception handling.
        backend, _ = backend_and_capture
        try:
            buf = backend.read()
            assert buf.shape == (0, CHANNELS)
            assert buf.dtype == np.float32
        finally:
            backend.close()

    def test_returns_queued_samples_as_ndarray(
        self,
        backend_and_capture: tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture],
    ):
        # Round-trip a known payload to confirm the bytes -> (N, 2)
        # float32 reshape is correct.
        backend, fake = backend_and_capture
        payload = np.array(
            [[0.25, -0.5], [1.0, -1.0], [0.0, 0.0]],
            dtype=np.float32,
        )
        fake.emit_samples(payload)
        try:
            buf = backend.read()
            np.testing.assert_array_equal(buf, payload)
            assert buf.shape == (3, CHANNELS)
            assert buf.dtype == np.float32
        finally:
            backend.close()

    def test_returned_array_is_writable(
        self,
        backend_and_capture: tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture],
    ):
        # np.frombuffer on bytes returns a read-only view; the backend
        # must copy so consumers (sinks, DSP code) can mutate freely.
        backend, fake = backend_and_capture
        fake.emit_samples(np.ones((2, CHANNELS), dtype=np.float32))
        try:
            buf = backend.read()
            buf[0, 0] = -1.0  # would raise on a read-only view
            assert buf[0, 0] == -1.0
        finally:
            backend.close()

    def test_truncates_partial_frame_with_warning(
        self,
        backend_and_capture: tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture],
        caplog: pytest.LogCaptureFixture,
    ):
        # If proc-tap ever returns a partial frame (e.g. 5 floats for a
        # stereo stream), the backend should drop the trailing samples
        # and log a warning rather than silently mis-frame the rest.
        backend, fake = backend_and_capture
        bad_payload = np.array(
            [0.1, 0.2, 0.3, 0.4, 0.5],  # 5 floats = 2 stereo frames + 1 leftover
            dtype=np.float32,
        )
        fake.enqueue_bytes(bad_payload.tobytes())

        with caplog.at_level(logging.WARNING, logger="vrcpilot.speaker.windows"):
            try:
                buf = backend.read()
            finally:
                backend.close()

        assert buf.shape == (2, CHANNELS)
        np.testing.assert_array_equal(
            buf,
            np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
        )
        assert any("not divisible by" in r.getMessage() for r in caplog.records)

    def test_read_after_close_raises(
        self,
        backend_and_capture: tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture],
    ):
        backend, _ = backend_and_capture
        backend.close()
        with pytest.raises(RuntimeError, match="closed"):
            backend.read()


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_invokes_stop_then_close(
        self,
        backend_and_capture: tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture],
    ):
        backend, fake = backend_and_capture
        backend.close()
        assert fake.stop_calls == 1
        assert fake.close_calls == 1

    def test_close_is_idempotent(
        self,
        backend_and_capture: tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture],
    ):
        backend, fake = backend_and_capture
        backend.close()
        backend.close()
        backend.close()
        # The underlying proc-tap stop/close must run exactly once even
        # with many backend.close calls.
        assert fake.stop_calls == 1
        assert fake.close_calls == 1

    def test_stop_failure_is_warned_not_raised(
        self,
        backend_and_capture: tuple[ProcTapSpeakerBackend, FakeProcessAudioCapture],
    ):
        # Cleanup is best-effort: a misbehaving proc-tap must not stop
        # us from closing the rest of the chain (and definitely must
        # not raise from a SpeakerLoop's __exit__).
        backend, fake = backend_and_capture
        fake.stop_raises = RuntimeError("device disconnected")
        with pytest.warns(UserWarning, match="proc-tap stop failed"):
            backend.close()
        assert fake.close_calls == 1
