"""Behaviour tests for :class:`vrcpilot.capture.loop.CaptureLoop`.

CaptureLoop is the unit under test. Its internal collaborator —
:class:`vrcpilot.capture.session.Capture` — is the in-house abstraction
that hides the OS backend; we substitute it with :class:`FakeCapture`
(an in-house ABC fake under ``tests/fakes/``) via ``mocker.patch`` on
the ``Capture`` symbol re-imported by ``capture.loop``. This is a
deliberate integration-with-fakes setup: the real loop threading code
runs unmodified, while the frame source is deterministic.

What is not tested here:

- The real platform backend (WGC / X11). That belongs to the
  ``test_windows.py`` / ``test_linux.py`` integration-real modules.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeCapture
from vrcpilot.capture import CaptureLoop


def _install_fake_capture(mocker: MockerFixture, fake: FakeCapture) -> FakeCapture:
    """Replace the ``Capture`` symbol seen by ``capture.loop`` with ``fake``.

    Returns the fake unchanged so the call site reads as a single
    expression. ``Capture`` is vrcpilot's own abstraction, so this
    substitution is fake-on-own-ABC, not third-party mocking.
    """
    mocker.patch("vrcpilot.capture.loop.Capture", return_value=fake)
    return fake


def _noop_callback(_: np.ndarray) -> None:
    return None


class TestCaptureLoopConstruction:
    """``__init__`` argument validation and forwarding to ``Capture``."""

    @pytest.mark.parametrize("fps", [0.0, -0.1, -10.0])
    def test_non_positive_fps_raises_value_error(
        self, mocker: MockerFixture, fps: float
    ):
        # Spec: fps must be strictly positive. The check happens before
        # Capture construction so a fps misuse never spends resources on
        # opening a backend.
        _install_fake_capture(mocker, FakeCapture())
        with pytest.raises(ValueError, match="fps must be > 0"):
            CaptureLoop(_noop_callback, fps=fps)

    def test_capture_construction_failure_propagates_unchanged(
        self, mocker: MockerFixture
    ):
        # Spec: errors raised while constructing the internal Capture
        # (VRChat not running, multi-instance without pid, etc.) must
        # surface unchanged so callers see one consistent error from
        # CaptureLoop() as they would from Capture().
        mocker.patch(
            "vrcpilot.capture.loop.Capture",
            side_effect=RuntimeError("VRChat is not running"),
        )
        with pytest.raises(RuntimeError, match="VRChat is not running"):
            CaptureLoop(_noop_callback, fps=30.0)

    def test_forwards_frame_timeout_and_pid_to_capture(self, mocker: MockerFixture):
        # Spec: ``frame_timeout`` and ``pid`` are passed through to the
        # owned Capture so the public surface stays consistent. This is
        # a boundary assertion on the in-house Capture abstraction.
        capture_factory = mocker.patch(
            "vrcpilot.capture.loop.Capture", return_value=FakeCapture()
        )
        CaptureLoop(_noop_callback, fps=30.0, frame_timeout=1.5, pid=98765)
        capture_factory.assert_called_once_with(frame_timeout=1.5, pid=98765)

    def test_pid_defaults_to_none(self, mocker: MockerFixture):
        # Spec: omitting ``pid`` forwards ``None`` so the auto-resolve
        # path in Capture runs unchanged.
        capture_factory = mocker.patch(
            "vrcpilot.capture.loop.Capture", return_value=FakeCapture()
        )
        CaptureLoop(_noop_callback, fps=30.0)
        _args, kwargs = capture_factory.call_args
        assert kwargs["pid"] is None


class TestCaptureLoopRun:
    """Loop body: callback delivery and pacing."""

    def test_callback_receives_ndarray_frames(self, mocker: MockerFixture):
        # Spec: each tick of the loop reads one frame from Capture and
        # invokes the user callback with it. Wait for several ticks to
        # confirm the worker thread is actually iterating rather than
        # primed-and-stalled.
        _install_fake_capture(mocker, FakeCapture())
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

    def test_loop_roughly_respects_target_fps(self, mocker: MockerFixture):
        # Spec: the loop paces ticks at the configured fps; it must
        # neither free-run nor stall completely. Bounds are wide to
        # tolerate scheduler jitter on shared CI runners while still
        # catching either failure mode.
        _install_fake_capture(mocker, FakeCapture())
        count = 0

        def cb(_: np.ndarray) -> None:
            nonlocal count
            count += 1

        loop = CaptureLoop(cb, fps=20.0)
        loop.start()
        time.sleep(0.6)
        loop.close()

        # Ideal at 20 fps over 0.6 s is 12 ticks. Accept [4, 24] to
        # absorb startup latency and scheduling but still flag both
        # extremes (~0 = stalled, >>24 = runaway).
        assert 4 <= count <= 24, f"unexpected tick count: {count}"


class TestCaptureLoopLifecycle:
    """``start`` / ``stop`` / ``close`` / context-manager contract."""

    def test_stop_then_start_resumes_without_closing_capture(
        self, mocker: MockerFixture
    ):
        # Spec: ``stop`` pauses the worker but does not close the
        # underlying Capture; users can resume the loop without
        # re-opening the (expensive) backend session.
        fake = _install_fake_capture(mocker, FakeCapture())

        loop = CaptureLoop(_noop_callback, fps=200.0)
        loop.start()
        time.sleep(0.05)
        loop.stop()
        assert fake.close_calls == 0
        assert not loop.is_running

        ticks_before_resume = fake.read_calls
        loop.start()
        time.sleep(0.05)
        loop.close()

        # After resume the loop should produce additional reads.
        assert fake.read_calls > ticks_before_resume
        # Capture is closed exactly once across the whole lifecycle.
        assert fake.close_calls == 1

    def test_double_start_raises(self, mocker: MockerFixture):
        # Spec: starting an already-running loop is a misuse that we
        # surface immediately rather than silently spawn two workers.
        _install_fake_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop_callback, fps=50.0)
        loop.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                loop.start()
        finally:
            loop.close()

    def test_start_after_close_raises(self, mocker: MockerFixture):
        # Spec: a closed loop cannot be restarted (the underlying
        # Capture is gone). The error names the closed state so callers
        # know they must construct a fresh CaptureLoop.
        _install_fake_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop_callback, fps=50.0)
        loop.close()
        with pytest.raises(RuntimeError, match="closed"):
            loop.start()

    def test_stop_is_idempotent_across_states(self, mocker: MockerFixture):
        # Spec: ``stop`` is the public "make sure the loop is not
        # running" primitive; callers should not have to track state.
        # It must be safe before start, after stop, and after close.
        _install_fake_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop_callback, fps=50.0)
        loop.stop()  # before start
        loop.start()
        loop.stop()
        loop.stop()  # after stop
        loop.close()
        loop.stop()  # after close

    def test_close_is_idempotent(self, mocker: MockerFixture):
        # Spec: ``close`` may be reached from ``__exit__``, an explicit
        # call, and a finally block in the same run; doubling up must
        # be safe and must release the underlying Capture exactly once.
        fake = _install_fake_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop_callback, fps=50.0)
        loop.close()
        loop.close()
        loop.close()
        assert fake.close_calls == 1

    def test_close_stops_a_running_loop(self, mocker: MockerFixture):
        # Spec: closing while the worker is alive joins it and closes
        # Capture, so afterwards ``is_running`` is False.
        fake = _install_fake_capture(mocker, FakeCapture())
        loop = CaptureLoop(_noop_callback, fps=200.0)
        loop.start()
        time.sleep(0.05)
        loop.close()
        assert not loop.is_running
        assert fake.close_calls == 1

    def test_context_manager_closes_on_exit(self, mocker: MockerFixture):
        # Spec: the ``with`` form closes the loop on scope exit; this is
        # the documented preferred lifecycle and what users will read in
        # the README examples.
        fake = _install_fake_capture(mocker, FakeCapture())
        with CaptureLoop(_noop_callback, fps=200.0) as loop:
            loop.start()
            time.sleep(0.05)
        assert not loop.is_running
        assert fake.close_calls == 1


class TestCaptureLoopExceptionPropagation:
    """Worker-thread exceptions surface on the next stop / close call."""

    def test_callback_exception_re_raised_on_stop(self, mocker: MockerFixture):
        # Spec: an exception from the user callback terminates the
        # worker; the exception is held and re-raised on the next
        # ``stop`` (or ``close``) so a silent thread death is impossible.
        _install_fake_capture(mocker, FakeCapture())

        class _Boom(RuntimeError):
            pass

        def cb(_: np.ndarray) -> None:
            raise _Boom("callback failed")

        loop = CaptureLoop(cb, fps=200.0)
        loop.start()
        # Wait for the worker to die so the recorded exception is
        # available when we call stop().
        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        with pytest.raises(_Boom, match="callback failed"):
            loop.stop()
        # Spec: the held exception is cleared after re-raise so a
        # follow-up stop / close does not raise twice.
        loop.stop()
        loop.close()

    def test_read_exception_re_raised_on_close(self, mocker: MockerFixture):
        # Spec: a Capture.read() failure is treated the same as a
        # callback failure — the worker dies, the exception is held,
        # and the next close() surfaces it.
        boom = RuntimeError("read blew up")
        _install_fake_capture(mocker, FakeCapture(read_side_effect=boom))

        loop = CaptureLoop(_noop_callback, fps=200.0)
        loop.start()
        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        with pytest.raises(RuntimeError, match="read blew up"):
            loop.close()

    def test_loop_terminates_when_exception_occurs(self, mocker: MockerFixture):
        # Spec: after an exception the worker thread exits; ``is_running``
        # must report False so callers can poll for completion without
        # racing the (still-blocked) stop() call.
        _install_fake_capture(mocker, FakeCapture(read_side_effect=RuntimeError("x")))
        loop = CaptureLoop(_noop_callback, fps=200.0)
        loop.start()
        deadline = time.perf_counter() + 2.0
        while loop.is_running and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert not loop.is_running
        with pytest.raises(RuntimeError):
            loop.close()


class TestCaptureLoopReentrancy:
    """Calling ``stop`` from inside the user callback."""

    def test_stop_from_callback_does_not_deadlock(self, mocker: MockerFixture):
        # Spec: ``stop`` may be invoked from the worker thread itself
        # (a user callback decides to stop). The implementation must
        # detect the self-thread case and skip the join, otherwise the
        # worker would block trying to join itself. We use a watchdog
        # to fail fast rather than hang the whole pytest session.
        _install_fake_capture(mocker, FakeCapture())
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
