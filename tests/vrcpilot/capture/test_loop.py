"""Tests for :class:`vrcpilot.capture.loop.CaptureLoop`.

The internal :class:`Capture` is patched in the loop's own module
(``vrcpilot.capture.loop.Capture``) with the canonical
:class:`tests.fakes.FakeCapture` whose ``read()`` yields real
``numpy.ndarray`` instances. This keeps the OS-dependent backend
(WGC / X11) out of unit tests while still exercising the genuine
threading machinery in :class:`CaptureLoop`.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeCapture
from vrcpilot.capture import CaptureLoop


def _patch_capture(mocker: MockerFixture, fake: FakeCapture) -> FakeCapture:
    """Patch the ``Capture`` reference inside the loop module.

    The CaptureLoop is the unit under test; the platform-backed Capture
    it owns is internal collaboration that we substitute
    deterministically.
    """
    mocker.patch("vrcpilot.capture.loop.Capture", return_value=fake)
    return fake


def _noop(_: np.ndarray) -> None:
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCaptureLoop:
    # --- construction / validation -------------------------------------

    @pytest.mark.parametrize("fps", [0.0, -0.1, -10.0])
    def test_rejects_non_positive_fps(self, mocker: MockerFixture, fps: float):
        # fps <= 0 would either spin forever or divide by zero downstream;
        # we surface the misuse at construction time rather than at start().
        _patch_capture(mocker, FakeCapture())
        with pytest.raises(ValueError, match="fps must be > 0"):
            CaptureLoop(_noop, fps=fps)

    def test_propagates_capture_init_failure(self, mocker: MockerFixture):
        # CaptureLoop owns the Capture; if construction fails (e.g. VRChat
        # not running) the error must surface unchanged so callers can
        # match on the same RuntimeError they would see from Capture().
        mocker.patch(
            "vrcpilot.capture.loop.Capture",
            side_effect=RuntimeError("VRChat is not running"),
        )
        with pytest.raises(RuntimeError, match="VRChat is not running"):
            CaptureLoop(_noop, fps=30.0)

    def test_pid_forwarded_to_capture(self, mocker: MockerFixture):
        # ``pid`` is the disambiguator on multi-instance setups; the
        # loop must forward it (along with ``frame_timeout``) to the
        # internally-owned Capture so users see one consistent surface.
        capture_cls = mocker.patch(
            "vrcpilot.capture.loop.Capture", return_value=FakeCapture()
        )
        CaptureLoop(_noop, fps=30.0, frame_timeout=1.5, pid=98765)
        capture_cls.assert_called_once_with(frame_timeout=1.5, pid=98765)

    def test_pid_defaults_to_none(self, mocker: MockerFixture):
        # Omitting ``pid`` must forward ``None`` so ``Capture`` (and
        # downstream ``resolve_pid``) handles the auto-resolve path the
        # same way as a direct call.
        capture_cls = mocker.patch(
            "vrcpilot.capture.loop.Capture", return_value=FakeCapture()
        )
        CaptureLoop(_noop, fps=30.0)
        _args, kwargs = capture_cls.call_args
        assert kwargs["pid"] is None

    # --- basic loop behaviour ------------------------------------------

    def test_invokes_callback_with_frames(self, mocker: MockerFixture):
        # The callback must receive ndarrays from read(); a few ticks at
        # high fps confirms the loop is actually running, not just primed.
        _patch_capture(mocker, FakeCapture())
        received: list[np.ndarray] = []
        ready = threading.Event()

        def cb(frame: np.ndarray) -> None:
            received.append(frame)
            if len(received) >= 3:
                ready.set()

        loop = CaptureLoop(cb, fps=200.0)
        loop.start()
        try:
            assert ready.wait(2.0), "callback was not invoked enough times"
        finally:
            loop.close()

        assert all(isinstance(f, np.ndarray) for f in received)
        assert all(f.shape == (4, 4, 3) for f in received)

    def test_respects_target_fps(self, mocker: MockerFixture):
        # Drive at fps=20 for ~0.6s and check the realised rate is in a
        # generous window. The exact value depends on scheduler jitter so
        # the bounds are wide; the point is to detect "free running" or
        # "completely stalled" loops, not to benchmark.
        _patch_capture(mocker, FakeCapture())
        count = 0

        def cb(_: np.ndarray) -> None:
            nonlocal count
            count += 1

        loop = CaptureLoop(cb, fps=20.0)
        loop.start()
        time.sleep(0.6)
        loop.close()

        # At 20 fps over 0.6s the ideal count is 12. Allow [4, 24] to
        # absorb startup latency and CI scheduler hiccups while still
        # catching a runaway loop (which would push count >> 24).
        assert 4 <= count <= 24, f"unexpected tick count: {count}"

    # --- lifecycle ------------------------------------------------------

    def test_stop_then_start_resumes(self, mocker: MockerFixture):
        # stop() must not close Capture; users can pause and resume the
        # loop without rebuilding the (expensive) backend session.
        fake = _patch_capture(mocker, FakeCapture())

        loop = CaptureLoop(_noop, fps=200.0)
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
        _patch_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop, fps=50.0)
        loop.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                loop.start()
        finally:
            loop.close()

    def test_start_after_close_raises(self, mocker: MockerFixture):
        _patch_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop, fps=50.0)
        loop.close()
        with pytest.raises(RuntimeError, match="closed"):
            loop.start()

    def test_stop_is_idempotent(self, mocker: MockerFixture):
        # stop() must be safe before start(), after stop(), and after
        # close(); it is the public "make sure the loop is not running"
        # primitive and callers should not have to track state.
        _patch_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop, fps=50.0)
        loop.stop()
        loop.start()
        loop.stop()
        loop.stop()
        loop.close()
        loop.stop()

    def test_close_is_idempotent(self, mocker: MockerFixture):
        fake = _patch_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop, fps=50.0)
        loop.close()
        loop.close()
        loop.close()
        # Underlying Capture.close runs only once even with many
        # CaptureLoop.close calls.
        assert fake.close_calls == 1

    def test_close_stops_running_loop(self, mocker: MockerFixture):
        fake = _patch_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop, fps=200.0)
        loop.start()
        time.sleep(0.05)
        loop.close()
        assert not loop.is_running
        assert fake.close_calls == 1

    def test_context_manager_closes(self, mocker: MockerFixture):
        fake = _patch_capture(mocker, FakeCapture())
        with CaptureLoop(_noop, fps=200.0) as loop:
            loop.start()
            time.sleep(0.05)
        assert not loop.is_running
        assert fake.close_calls == 1

    # --- exception propagation -----------------------------------------

    def test_callback_exception_re_raised_on_stop(self, mocker: MockerFixture):
        # A callback that raises terminates the worker; the exception is
        # held and surfaced on the next stop()/close() call so the user
        # cannot miss a silent thread death.
        _patch_capture(mocker, FakeCapture())

        class _Boom(RuntimeError):
            pass

        def cb(_: np.ndarray) -> None:
            raise _Boom("callback failed")

        loop = CaptureLoop(cb, fps=200.0)
        loop.start()
        # Wait for the worker to die so stop() sees the recorded exception.
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
        _patch_capture(mocker, FakeCapture(read_side_effect=boom))

        loop = CaptureLoop(_noop, fps=200.0)
        loop.start()
        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        with pytest.raises(RuntimeError, match="read blew up"):
            loop.close()

    def test_loop_stops_on_exception(self, mocker: MockerFixture):
        _patch_capture(mocker, FakeCapture(read_side_effect=RuntimeError("x")))
        loop = CaptureLoop(_noop, fps=200.0)
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
        # implementation is required to skip self-join when invoked from
        # the loop thread itself. We use a watchdog timer to fail fast
        # rather than hang the test session.
        _patch_capture(mocker, FakeCapture())
        ticks = 0

        def cb(_: np.ndarray) -> None:
            nonlocal ticks
            ticks += 1
            if ticks == 1:
                loop.stop()

        loop = CaptureLoop(cb, fps=200.0)
        loop.start()

        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert not loop.is_running, "loop did not exit after self-stop"
        loop.close()
