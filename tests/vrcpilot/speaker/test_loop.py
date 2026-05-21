"""Tests for :class:`vrcpilot.speaker.loop.SpeakerLoop`.

The internal :class:`Speaker` is patched in the loop's own module
(``vrcpilot.speaker.loop.Speaker``) with the canonical
:class:`tests.fakes.FakeSpeaker` whose ``read`` yields real
``numpy.ndarray`` instances. This keeps the OS-dependent proc-tap
native backend out of unit tests while still exercising the genuine
threading machinery in :class:`SpeakerLoop`.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from numpy.typing import NDArray
from pytest_mock import MockerFixture

from tests.fakes import FakeSpeaker
from vrcpilot.speaker.base import CHANNELS
from vrcpilot.speaker.loop import SpeakerLoop


def _patch_speaker(mocker: MockerFixture, fake: FakeSpeaker) -> FakeSpeaker:
    """Patch the ``Speaker`` reference inside the loop module.

    Mirrors the ``_patch_capture`` helper in
    :mod:`tests.vrcpilot.capture.test_loop`. The SpeakerLoop is the
    unit under test; the Speaker it owns is internal collaboration we
    substitute deterministically.
    """
    mocker.patch("vrcpilot.speaker.loop.Speaker", return_value=fake)
    return fake


def _noop(_: NDArray[np.float32]) -> None:
    return None


class TestSpeakerLoop:
    # --- construction / validation -------------------------------------

    @pytest.mark.parametrize("bad", [0.0, -0.1, -1.0])
    def test_rejects_non_positive_chunk_seconds(
        self,
        mocker: MockerFixture,
        bad: float,
    ):
        # chunk_seconds <= 0 would either spin the worker or divide by
        # zero somewhere downstream; we surface the misuse at
        # construction time rather than at start().
        _patch_speaker(mocker, FakeSpeaker())
        with pytest.raises(ValueError, match="chunk_seconds must be > 0"):
            SpeakerLoop(_noop, chunk_seconds=bad)

    def test_propagates_speaker_init_failure(self, mocker: MockerFixture):
        # SpeakerLoop owns the Speaker; if construction fails (e.g.
        # VRChat not running) the error must surface unchanged so
        # callers can match on the same RuntimeError they would see
        # from Speaker().
        mocker.patch(
            "vrcpilot.speaker.loop.Speaker",
            side_effect=RuntimeError("VRChat is not running"),
        )
        with pytest.raises(RuntimeError, match="VRChat is not running"):
            SpeakerLoop(_noop)

    def test_forwards_kwargs_to_speaker(self, mocker: MockerFixture):
        # read_timeout must reach the wrapped Speaker verbatim;
        # otherwise the loop is unable to expose a custom timeout.
        spy = mocker.patch(
            "vrcpilot.speaker.loop.Speaker",
            return_value=FakeSpeaker(),
        )
        loop = SpeakerLoop(_noop, read_timeout=1.25)
        try:
            spy.assert_called_once_with(read_timeout=1.25)
        finally:
            loop.close()

    # --- basic loop behaviour ------------------------------------------

    def test_invokes_callback_with_chunks(self, mocker: MockerFixture):
        # The callback must receive ndarrays from read(); a few ticks
        # at a small chunk_seconds confirms the loop is actually
        # running, not just primed.
        payload = np.full((4, CHANNELS), 0.5, dtype=np.float32)
        _patch_speaker(mocker, FakeSpeaker(chunk=payload))

        received: list[NDArray[np.float32]] = []
        ready = threading.Event()

        def cb(chunk: NDArray[np.float32]) -> None:
            received.append(chunk)
            if len(received) >= 3:
                ready.set()

        loop = SpeakerLoop(cb, chunk_seconds=0.005)
        loop.start()
        try:
            assert ready.wait(2.0), "callback was not invoked enough times"
        finally:
            loop.close()

        assert all(isinstance(c, np.ndarray) for c in received)
        assert all(c.shape == (4, CHANNELS) for c in received)
        np.testing.assert_array_equal(received[0], payload)

    def test_empty_chunks_are_forwarded(self, mocker: MockerFixture):
        # An empty read is a valid "silence tick" signal; the loop must
        # not silently drop it or downstream consumers cannot observe
        # quiet periods.
        _patch_speaker(mocker, FakeSpeaker())  # default chunk is empty

        received: list[NDArray[np.float32]] = []
        ready = threading.Event()

        def cb(chunk: NDArray[np.float32]) -> None:
            received.append(chunk)
            if len(received) >= 2:
                ready.set()

        loop = SpeakerLoop(cb, chunk_seconds=0.005)
        loop.start()
        try:
            assert ready.wait(2.0)
        finally:
            loop.close()

        assert all(c.shape == (0, CHANNELS) for c in received)

    # --- lifecycle -----------------------------------------------------

    def test_stop_then_start_resumes(self, mocker: MockerFixture):
        # stop() must not close the Speaker; users can pause and
        # resume the loop without rebuilding the backend session.
        fake = _patch_speaker(mocker, FakeSpeaker())

        loop = SpeakerLoop(_noop, chunk_seconds=0.005)
        loop.start()
        time.sleep(0.05)
        loop.stop()
        assert fake.close_calls == 0
        assert not loop.is_running

        first_round = fake.read_calls
        loop.start()
        time.sleep(0.05)
        loop.close()

        assert fake.read_calls > first_round
        assert fake.close_calls == 1

    def test_double_start_raises(self, mocker: MockerFixture):
        _patch_speaker(mocker, FakeSpeaker())
        loop = SpeakerLoop(_noop, chunk_seconds=0.02)
        loop.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                loop.start()
        finally:
            loop.close()

    def test_start_after_close_raises(self, mocker: MockerFixture):
        _patch_speaker(mocker, FakeSpeaker())
        loop = SpeakerLoop(_noop, chunk_seconds=0.02)
        loop.close()
        with pytest.raises(RuntimeError, match="closed"):
            loop.start()

    def test_stop_is_idempotent(self, mocker: MockerFixture):
        # stop() must be safe before start(), after stop(), and after
        # close(); it is the public "make sure the loop is not running"
        # primitive and callers should not have to track state.
        _patch_speaker(mocker, FakeSpeaker())
        loop = SpeakerLoop(_noop, chunk_seconds=0.02)
        loop.stop()
        loop.start()
        loop.stop()
        loop.stop()
        loop.close()
        loop.stop()

    def test_close_is_idempotent(self, mocker: MockerFixture):
        fake = _patch_speaker(mocker, FakeSpeaker())
        loop = SpeakerLoop(_noop, chunk_seconds=0.02)
        loop.close()
        loop.close()
        loop.close()
        # Underlying Speaker.close runs only once even with many
        # SpeakerLoop.close calls.
        assert fake.close_calls == 1

    def test_close_stops_running_loop(self, mocker: MockerFixture):
        fake = _patch_speaker(mocker, FakeSpeaker())
        loop = SpeakerLoop(_noop, chunk_seconds=0.005)
        loop.start()
        time.sleep(0.05)
        loop.close()
        assert not loop.is_running
        assert fake.close_calls == 1

    def test_context_manager_closes(self, mocker: MockerFixture):
        fake = _patch_speaker(mocker, FakeSpeaker())
        with SpeakerLoop(_noop, chunk_seconds=0.005) as loop:
            loop.start()
            time.sleep(0.05)
        assert not loop.is_running
        assert fake.close_calls == 1

    # --- exception propagation -----------------------------------------

    def test_callback_exception_re_raised_on_stop(self, mocker: MockerFixture):
        # A callback that raises terminates the worker; the exception
        # is held and surfaced on the next stop()/close() call so the
        # user cannot miss a silent thread death.
        _patch_speaker(mocker, FakeSpeaker())

        class _Boom(RuntimeError):
            pass

        def cb(_: NDArray[np.float32]) -> None:
            raise _Boom("callback failed")

        loop = SpeakerLoop(cb, chunk_seconds=0.005)
        loop.start()
        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        with pytest.raises(_Boom, match="callback failed"):
            loop.stop()
        # The exception is cleared after re-raise so a follow-up stop
        # does not raise twice.
        loop.stop()
        loop.close()

    def test_read_exception_re_raised_on_close(self, mocker: MockerFixture):
        boom = RuntimeError("read blew up")
        _patch_speaker(mocker, FakeSpeaker(read_side_effect=boom))

        loop = SpeakerLoop(_noop, chunk_seconds=0.005)
        loop.start()
        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        with pytest.raises(RuntimeError, match="read blew up"):
            loop.close()

    def test_loop_stops_on_exception(self, mocker: MockerFixture):
        _patch_speaker(
            mocker,
            FakeSpeaker(read_side_effect=RuntimeError("x")),
        )
        loop = SpeakerLoop(_noop, chunk_seconds=0.005)
        loop.start()
        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert not loop.is_running
        with pytest.raises(RuntimeError):
            loop.close()

    # --- thread-safety: stop from inside callback ----------------------

    def test_stop_from_callback_does_not_deadlock(self, mocker: MockerFixture):
        # Calling stop() from the worker thread must not deadlock - the
        # implementation is required to skip self-join when invoked
        # from the loop thread itself. We use a watchdog timer to fail
        # fast rather than hang the test session.
        _patch_speaker(mocker, FakeSpeaker())
        ticks = 0

        def cb(_: NDArray[np.float32]) -> None:
            nonlocal ticks
            ticks += 1
            if ticks == 1:
                loop.stop()

        loop = SpeakerLoop(cb, chunk_seconds=0.005)
        loop.start()

        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert not loop.is_running, "loop did not exit after self-stop"
        loop.close()
