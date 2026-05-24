"""Tests for :class:`vrcpilot.speaker.loop.SpeakerLoop`.

``SpeakerLoop`` owns its inner :class:`Speaker` collaborator; tests
substitute that single seam with :class:`tests.fakes.FakeSpeaker` --
the **self-owned ABC mirror** explicitly allowed by the testing skill
(``Speaker`` is a vrcpilot-internal class, not a 3rd-party library
surface). The substitution keeps the OS-dependent backend out of unit
tests while exercising the real threading machinery of the loop.
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
    """Substitute the ``Speaker`` factory inside the loop's own module.

    Patching the binding inside ``vrcpilot.speaker.loop`` (rather than
    the source module) is the canonical pattern for "replace the
    collaborator that the unit under test imports". Returns the fake
    so tests can inspect read / close call counts.
    """
    mocker.patch("vrcpilot.speaker.loop.Speaker", return_value=fake)
    return fake


def _noop(_: NDArray[np.float32]) -> None:
    return None


class TestConstruction:
    @pytest.mark.parametrize("bad", [0.0, -0.1, -1.0])
    def test_non_positive_chunk_seconds_rejected_before_speaker_open(
        self, mocker: MockerFixture, bad: float
    ) -> None:
        # Validation must fire before the Speaker factory runs --
        # otherwise a misuse opens a backend that immediately needs
        # closing, surfacing as a "VRChat not running" error far from
        # the actual caller bug.
        spy = mocker.patch("vrcpilot.speaker.loop.Speaker", return_value=FakeSpeaker())
        with pytest.raises(ValueError, match="chunk_seconds must be > 0"):
            SpeakerLoop(_noop, chunk_seconds=bad)
        spy.assert_not_called()

    def test_forwards_kwargs_to_owned_speaker(self, mocker: MockerFixture) -> None:
        # The loop is a thin facade: read_timeout / pid must reach the
        # owned Speaker verbatim. If kwargs were silently dropped, a
        # caller pinning a particular VRChat instance would end up
        # captured against the wrong process.
        spy = mocker.patch("vrcpilot.speaker.loop.Speaker", return_value=FakeSpeaker())
        loop = SpeakerLoop(_noop, read_timeout=1.25, pid=12345)
        try:
            spy.assert_called_once_with(read_timeout=1.25, pid=12345)
        finally:
            loop.close()

    def test_propagates_speaker_init_failure(self, mocker: MockerFixture) -> None:
        # If the inner Speaker can't open (VRChat not running, missing
        # CLI, etc.) the loop must let the error propagate -- callers
        # rely on matching the same RuntimeError they would see from
        # bare ``Speaker()``.
        mocker.patch(
            "vrcpilot.speaker.loop.Speaker",
            side_effect=RuntimeError("VRChat is not running"),
        )
        with pytest.raises(RuntimeError, match="VRChat is not running"):
            SpeakerLoop(_noop)


class TestRunningLoop:
    def test_forwards_chunks_to_callback(self, mocker: MockerFixture) -> None:
        # The whole point of the loop: ``Speaker.read`` chunks must
        # reach the user callback unmodified. Pin a recognisable
        # ndarray and confirm the first delivered chunk matches.
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
        np.testing.assert_array_equal(received[0], payload)

    def test_empty_chunks_are_forwarded(self, mocker: MockerFixture) -> None:
        # An empty read is the documented "silence tick" signal.
        # Swallowing it would deny downstream consumers (sinks, VAD)
        # the ability to detect quiet periods.
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


class TestLifecycle:
    def test_stop_then_start_resumes(self, mocker: MockerFixture) -> None:
        # Pause / resume: stop() must NOT close the Speaker, only halt
        # the worker. Otherwise users could not gate audio capture
        # without paying the backend reconstruction cost.
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

    def test_double_start_raises(self, mocker: MockerFixture) -> None:
        _patch_speaker(mocker, FakeSpeaker())
        loop = SpeakerLoop(_noop, chunk_seconds=0.02)
        loop.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                loop.start()
        finally:
            loop.close()

    def test_start_after_close_raises(self, mocker: MockerFixture) -> None:
        _patch_speaker(mocker, FakeSpeaker())
        loop = SpeakerLoop(_noop, chunk_seconds=0.02)
        loop.close()
        with pytest.raises(RuntimeError, match="closed"):
            loop.start()

    def test_stop_is_idempotent_in_every_state(self, mocker: MockerFixture) -> None:
        # The public "make sure the loop is not running" primitive
        # must accept being called before start, between cycles, and
        # after close -- otherwise CLI shutdown paths grow defensive
        # state tracking.
        _patch_speaker(mocker, FakeSpeaker())
        loop = SpeakerLoop(_noop, chunk_seconds=0.02)
        loop.stop()
        loop.start()
        loop.stop()
        loop.stop()
        loop.close()
        loop.stop()

    def test_close_runs_inner_speaker_close_exactly_once(
        self, mocker: MockerFixture
    ) -> None:
        # SpeakerLoop owns the backend session; even when the loop's
        # own close is called many times, Speaker.close must fire
        # exactly once (the OS resource is single-shot).
        fake = _patch_speaker(mocker, FakeSpeaker())
        loop = SpeakerLoop(_noop, chunk_seconds=0.02)
        loop.close()
        loop.close()
        loop.close()
        assert fake.close_calls == 1

    def test_context_manager_closes_on_exit(self, mocker: MockerFixture) -> None:
        fake = _patch_speaker(mocker, FakeSpeaker())
        with SpeakerLoop(_noop, chunk_seconds=0.005) as loop:
            loop.start()
            time.sleep(0.05)
        assert not loop.is_running
        assert fake.close_calls == 1


class TestExceptionPropagation:
    def test_callback_exception_re_raised_on_stop_then_cleared(
        self, mocker: MockerFixture
    ) -> None:
        # A raising callback kills the worker; the exception must
        # surface from the next stop()/close() call (so users cannot
        # miss a silent thread death) and then be cleared so a second
        # stop is benign.
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
        # One-shot surfacing: second stop must not re-raise.
        loop.stop()
        loop.close()

    def test_read_exception_re_raised_on_close(self, mocker: MockerFixture) -> None:
        # If Speaker.read raises (backend died), the loop must surface
        # that on close so the user knows their capture is gone.
        boom = RuntimeError("read blew up")
        _patch_speaker(mocker, FakeSpeaker(read_side_effect=boom))

        loop = SpeakerLoop(_noop, chunk_seconds=0.005)
        loop.start()
        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        with pytest.raises(RuntimeError, match="read blew up"):
            loop.close()


class TestStopFromCallback:
    def test_stop_from_callback_does_not_deadlock(self, mocker: MockerFixture) -> None:
        # A callback calling loop.stop() must not deadlock -- the
        # implementation is required to skip self-join when invoked
        # from the loop thread. Watchdog timer fails fast rather than
        # hanging the test session.
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
