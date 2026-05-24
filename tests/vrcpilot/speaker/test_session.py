"""Platform-agnostic wrapper-plumbing tests for
:class:`vrcpilot.speaker.Speaker`.

The backend factory (``_select_speaker_backend``) is the single seam
exercised by these tests; substituting it with
:class:`tests.helpers.ImplSpeakerBackend` lets every wrapper concern
(validation, read-through, close idempotency, context manager,
exception transparency) be tested without any OS audio stack. The
factory is an internal own-class factory, so patching it is the
permitted "own-ABC swap" form -- not a mock of a 3rd-party surface or
of a free function inside our own code.

PID handling intentionally goes through the **real**
``vrcpilot.process.resolve_pid``: an explicit ``pid=`` short-circuits
to ``return pid`` unchanged, and ``pid=None`` consults the live
``psutil.process_iter`` (defaulted to an empty iterator by the project
autouse ``_no_real_vrchat`` fixture in ``tests/conftest.py``). This
keeps the resolve_pid call site real without mocking own code.

Platform-specific dispatch lives in the sibling
``test_session_linux.py`` / ``test_session_windows.py`` files so neither
``sys.platform`` monkeypatching nor cross-platform module imports are
needed here (both are banned by the testing skill).

Multi-instance routing (``VRChatMultipleInstancesError`` surfacing
when ``pid=None`` and two VRChats are running) is **not** covered here:
forcing two PIDs out of ``find_pids`` would require patching
``psutil.process_iter`` per-test, which the project conftest explicitly
forbids. That branch is covered end-to-end in ``tests/e2e/``.
"""

from __future__ import annotations

from typing import override

import numpy as np
import pytest
from numpy.typing import NDArray
from pytest_mock import MockerFixture

from tests.helpers import ImplSpeakerBackend
from vrcpilot.process import VRChatNotRunningError
from vrcpilot.speaker.base import CHANNELS
from vrcpilot.speaker.session import Speaker

# Any positive int works: ``resolve_pid(non_None)`` returns its
# argument unchanged without consulting the OS, so the wrapper plumbing
# can observe ``pid`` propagation without depending on a real process.
_EXPLICIT_PID = 4242


def _patch_backend_factory(
    mocker: MockerFixture, backend: ImplSpeakerBackend
) -> ImplSpeakerBackend:
    """Substitute the own-class backend factory with ``backend``.

    ``_select_speaker_backend`` is an internal factory that hands back
    a ``SpeakerBackend`` (own ABC) -- swapping it for a deterministic
    impl is the permitted "own-ABC seam" form.
    """
    mocker.patch(
        "vrcpilot.speaker.session._select_speaker_backend",
        return_value=backend,
    )
    return backend


class TestConstructionValidation:
    @pytest.mark.parametrize("bad_timeout", [0.0, -0.1, -1.0])
    def test_non_positive_read_timeout_rejected_before_backend_open(
        self, mocker: MockerFixture, bad_timeout: float
    ) -> None:
        # Validation must fire before the backend factory runs so the
        # user-visible error points at the caller misuse, not at
        # whatever proc-tap / PipeWire surfaces when handed a bogus
        # timeout.
        spy = mocker.patch(
            "vrcpilot.speaker.session._select_speaker_backend",
            return_value=ImplSpeakerBackend(),
        )
        with pytest.raises(ValueError, match="read_timeout must be > 0"):
            Speaker(read_timeout=bad_timeout, pid=_EXPLICIT_PID)
        spy.assert_not_called()


class TestPidResolution:
    def test_omitted_pid_with_no_vrchat_running_raises_not_running(
        self, mocker: MockerFixture
    ) -> None:
        # Contract: when ``pid=None`` and no VRChat process exists, the
        # resolve_pid failure must surface to the caller unchanged --
        # Speaker is not allowed to swallow it into a generic
        # RuntimeError or to instantiate the backend with a bogus PID.
        # The empty-process_iter state is provided by the autouse
        # ``_no_real_vrchat`` fixture in tests/conftest.py.
        backend_spy = mocker.patch(
            "vrcpilot.speaker.session._select_speaker_backend",
            return_value=ImplSpeakerBackend(),
        )

        with pytest.raises(VRChatNotRunningError):
            Speaker()

        # Backend must not be constructed when PID resolution fails:
        # there is no PID to bind to.
        backend_spy.assert_not_called()


class TestRead:
    def test_returns_backend_buffer_verbatim(self, mocker: MockerFixture) -> None:
        # ``Speaker.read`` is a pass-through: the wrapper must not
        # copy, slice, or modify what the backend returned. Anything
        # else would silently change the contract callers see.
        payload = np.full((8, CHANNELS), 0.25, dtype=np.float32)
        _patch_backend_factory(mocker, ImplSpeakerBackend(buffer=payload))

        with Speaker(pid=_EXPLICIT_PID) as speaker:
            buf = speaker.read()

        np.testing.assert_array_equal(buf, payload)
        assert buf.shape == (8, CHANNELS)
        assert buf.dtype == np.float32

    def test_read_after_close_raises_runtime_error(self, mocker: MockerFixture) -> None:
        # Lifecycle contract: post-close read surfaces as
        # RuntimeError, not as a backend-specific crash. The match on
        # "closed" pins the documented diagnostic substring.
        _patch_backend_factory(mocker, ImplSpeakerBackend())
        speaker = Speaker(pid=_EXPLICIT_PID)
        speaker.close()
        with pytest.raises(RuntimeError, match="Speaker is closed"):
            speaker.read()


class _CloseCountingBackend(ImplSpeakerBackend):
    """ImplSpeakerBackend that counts close invocations.

    Kept local because the count is only useful for the wrapper's
    idempotency assertion; the shared helper would not benefit from
    knowing about it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    @override
    def close(self) -> None:
        self.close_calls += 1
        super().close()


class TestClose:
    def test_backend_close_runs_exactly_once_no_matter_how_many_wrapper_closes(
        self, mocker: MockerFixture
    ) -> None:
        # The OS-level resource (proc-tap session, PipeWire pipeline)
        # is single-shot. Repeated wrapper closes must not re-enter
        # backend.close.
        backend = _CloseCountingBackend()
        _patch_backend_factory(mocker, backend)

        speaker = Speaker(pid=_EXPLICIT_PID)
        speaker.close()
        speaker.close()
        speaker.close()

        assert backend.close_calls == 1

    def test_context_manager_closes_and_marks_subsequent_read_as_error(
        self, mocker: MockerFixture
    ) -> None:
        backend = _CloseCountingBackend()
        _patch_backend_factory(mocker, backend)

        with Speaker(pid=_EXPLICIT_PID) as speaker:
            pass

        assert backend.close_calls == 1
        # After the with-block, the wrapper must treat read as a misuse.
        with pytest.raises(RuntimeError, match="closed"):
            speaker.read()

    def test_exit_does_not_suppress_inner_exception(
        self, mocker: MockerFixture
    ) -> None:
        # The context manager must propagate exceptions raised inside
        # the with-block; suppression would silently swallow real
        # failures (a notoriously hard-to-debug class of bug).
        _patch_backend_factory(mocker, ImplSpeakerBackend())

        class _Sentinel(Exception):
            pass

        with pytest.raises(_Sentinel):
            with Speaker(pid=_EXPLICIT_PID):
                raise _Sentinel("boom")
