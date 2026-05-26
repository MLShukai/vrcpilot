"""Integration-real tests for :class:`ProcTapSpeakerBackend`.

proc-tap is Windows-only (``sys_platform == 'win32'`` in pyproject), so
this file is module-level skipped on every other host. On a real
Windows runner the tests require a live VRChat process to capture from;
without one each test skips individually rather than failing.

Why no unit tests with fakes here: the previous test suite mocked the
``proctap.ProcessAudioCapture`` surface via ``FakeProcessAudioCapture``,
which the new testing skill explicitly forbids -- 3rd-party library
surfaces must not be mirrored. The plumbing the fakes used to cover
(start/stop/close ordering, byte-to-ndarray reshape) is now exercised
end-to-end against the real proc-tap session below.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("vrcpilot.speaker.windows is Windows-only", allow_module_level=True)

import time  # noqa: E402

import numpy as np  # noqa: E402

from vrcpilot import process  # noqa: E402
from vrcpilot.speaker.base import CHANNELS, SAMPLE_RATE  # noqa: E402
from vrcpilot.speaker.windows import ProcTapSpeakerBackend  # noqa: E402


@pytest.fixture
def live_vrchat_pid(monkeypatch: pytest.MonkeyPatch) -> int:
    """Skip unless a real VRChat process is observable.

    The autouse ``_no_real_vrchat`` fixture in ``tests/conftest.py``
    pins ``psutil.process_iter`` to an empty iterator; undoing the
    monkeypatch lets ``find_pids`` query the real OS. Returns the live
    PID so tests can pass it to ``ProcTapSpeakerBackend(pid=...)``.
    """
    monkeypatch.undo()
    pids = process.find_pids()
    if not pids:
        pytest.skip("VRChat is not running; cannot exercise proc-tap")
    return pids[0]


class TestConstructionValidation:
    @pytest.mark.parametrize("bad", [0.0, -0.5, -1.0])
    def test_non_positive_read_timeout_rejected(
        self, bad: float, live_vrchat_pid: int
    ) -> None:
        # Validation must fire before the proc-tap session is opened
        # so the caller sees a clear ValueError rather than a downstream
        # WASAPI error.
        with pytest.raises(ValueError, match="read_timeout must be > 0"):
            ProcTapSpeakerBackend(read_timeout=bad, pid=live_vrchat_pid)


class TestReadAgainstRealProcTap:
    def test_construct_then_close_against_live_vrchat(
        self, live_vrchat_pid: int
    ) -> None:
        # The most basic plumbing check: a backend can be opened and
        # closed against a real VRChat process without raising. If
        # this fails, every other read-side assertion is meaningless.
        backend = ProcTapSpeakerBackend(pid=live_vrchat_pid)
        backend.close()

    def test_read_returns_float32_stereo_array(self, live_vrchat_pid: int) -> None:
        # The ABC contract is shape (N, CHANNELS) with float32 dtype;
        # consumers index arr[:, 0] / arr[:, 1] directly. We loop until
        # a non-empty chunk arrives (VRChat may be silent at startup)
        # or the budget runs out -- the contract holds either way.
        backend = ProcTapSpeakerBackend(read_timeout=1.0, pid=live_vrchat_pid)
        try:
            deadline = time.monotonic() + 2.0
            chunk = backend.read()
            while chunk.shape[0] == 0 and time.monotonic() < deadline:
                chunk = backend.read()
        finally:
            backend.close()

        assert chunk.dtype == np.float32
        assert chunk.ndim == 2
        assert chunk.shape[1] == CHANNELS

    def test_sample_count_does_not_exceed_device_clock(
        self, live_vrchat_pid: int
    ) -> None:
        # Cumulative samples over 1s of reads must not exceed the
        # device's sample-rate ceiling (we allow 2x headroom for
        # proc-tap's internal buffering). If this trips, the read
        # path's reshape arithmetic is wrong.
        backend = ProcTapSpeakerBackend(read_timeout=0.2, pid=live_vrchat_pid)
        total_samples = 0
        try:
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                chunk = backend.read()
                assert chunk.dtype == np.float32
                assert chunk.ndim == 2
                assert chunk.shape[1] == CHANNELS
                total_samples += int(chunk.shape[0])
        finally:
            backend.close()
        if total_samples > 0:
            assert total_samples <= SAMPLE_RATE * 2


class TestCloseAgainstRealProcTap:
    def test_close_is_idempotent(self, live_vrchat_pid: int) -> None:
        # The wrapper documents idempotent close; proc-tap itself may
        # be less forgiving, so the wrapper must guard double-close.
        backend = ProcTapSpeakerBackend(pid=live_vrchat_pid)
        backend.close()
        backend.close()

    def test_read_after_close_raises_runtime_error(self, live_vrchat_pid: int) -> None:
        # Misuse contract: post-close read surfaces as RuntimeError,
        # not as a proc-tap segfault / hang.
        backend = ProcTapSpeakerBackend(pid=live_vrchat_pid)
        backend.close()
        with pytest.raises(RuntimeError, match="closed"):
            backend.read()
