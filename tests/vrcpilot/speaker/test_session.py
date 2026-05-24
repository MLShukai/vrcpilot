"""Platform-agnostic wrapper-plumbing tests for
:class:`vrcpilot.speaker.Speaker`.

The backend factory (``_select_speaker_backend``) is the single seam
exercised by these tests; substituting it with
:class:`tests.helpers.ImplSpeakerBackend` lets every wrapper concern
(validation, PID resolution, read-through, close idempotency, context
manager, exception transparency) be tested without any OS audio stack.

Platform-specific dispatch lives in the sibling
``test_session_linux.py`` / ``test_session_windows.py`` files so neither
``sys.platform`` monkeypatching nor cross-platform module imports are
needed here (both are banned by the testing skill).
"""

from __future__ import annotations

from typing import override

import numpy as np
import pytest
from numpy.typing import NDArray
from pytest_mock import MockerFixture

from tests.helpers import ImplSpeakerBackend
from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.speaker.base import CHANNELS
from vrcpilot.speaker.session import Speaker


@pytest.fixture(autouse=True)
def _pin_resolve_pid(mocker: MockerFixture) -> int:
    """Pin :func:`vrcpilot.process.resolve_pid` to a deterministic PID.

    The wrapper plumbing tests are not concerned with the process
    module; pinning a PID keeps every test off the live OS process
    iterator while still exercising the real call site. Individual
    tests that probe error paths override the patch via
    ``mocker.patch`` (the later patch shadows the autouse one).
    """
    pid = 4242
    mocker.patch("vrcpilot.speaker.session.resolve_pid", return_value=pid)
    return pid


def _patch_backend_factory(
    mocker: MockerFixture, backend: ImplSpeakerBackend
) -> ImplSpeakerBackend:
    """Substitute the dispatch with one that returns ``backend``.

    ``Speaker`` is the unit under test; the platform-backed
    SpeakerBackend it owns is internal collaboration that we replace
    deterministically.
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
            Speaker(read_timeout=bad_timeout)
        spy.assert_not_called()


class TestPidResolution:
    def test_resolve_pid_invoked_with_constructor_argument(
        self, mocker: MockerFixture
    ) -> None:
        # ``resolve_pid`` is the documented PID seam: an explicit pid
        # passes through verbatim; an omitted pid triggers the live
        # process-iterator probe. The wrapper must always go through
        # resolve_pid so the multi-instance error path stays uniform.
        explicit = 9999
        resolve_spy = mocker.patch(
            "vrcpilot.speaker.session.resolve_pid", return_value=explicit
        )
        factory_spy = mocker.patch(
            "vrcpilot.speaker.session._select_speaker_backend",
            return_value=ImplSpeakerBackend(),
        )
        with Speaker(pid=explicit):
            pass
        resolve_spy.assert_called_once_with(explicit)
        # The resolved PID must reach the backend factory; otherwise
        # the backend would query the wrong process.
        factory_spy.assert_called_once_with(read_timeout=2.0, pid=explicit)

    def test_multiple_instances_error_surfaces_unmodified(
        self, mocker: MockerFixture
    ) -> None:
        # When two VRChats are running, ``resolve_pid`` raises
        # ``VRChatMultipleInstancesError``; Speaker must surface that
        # unchanged so callers can disambiguate by passing ``pid=``,
        # AND must never construct the backend (because no PID was
        # actually chosen).
        mocker.patch(
            "vrcpilot.speaker.session.resolve_pid",
            side_effect=VRChatMultipleInstancesError([111, 222]),
        )
        backend_spy = mocker.patch(
            "vrcpilot.speaker.session._select_speaker_backend",
            return_value=ImplSpeakerBackend(),
        )
        with pytest.raises(VRChatMultipleInstancesError):
            Speaker()
        backend_spy.assert_not_called()


class TestRead:
    def test_returns_backend_buffer_verbatim(self, mocker: MockerFixture) -> None:
        # ``Speaker.read`` is a pass-through: the wrapper must not
        # copy, slice, or modify what the backend returned. Anything
        # else would silently change the contract callers see.
        payload = np.full((8, CHANNELS), 0.25, dtype=np.float32)
        _patch_backend_factory(mocker, ImplSpeakerBackend(buffer=payload))

        with Speaker() as speaker:
            buf = speaker.read()

        np.testing.assert_array_equal(buf, payload)
        assert buf.shape == (8, CHANNELS)
        assert buf.dtype == np.float32

    def test_read_after_close_raises_runtime_error(self, mocker: MockerFixture) -> None:
        # Lifecycle contract: post-close read surfaces as
        # RuntimeError, not as a backend-specific crash. The match on
        # "closed" pins the documented diagnostic substring.
        _patch_backend_factory(mocker, ImplSpeakerBackend())
        speaker = Speaker()
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

        speaker = Speaker()
        speaker.close()
        speaker.close()
        speaker.close()

        assert backend.close_calls == 1

    def test_context_manager_closes_and_marks_subsequent_read_as_error(
        self, mocker: MockerFixture
    ) -> None:
        backend = _CloseCountingBackend()
        _patch_backend_factory(mocker, backend)

        with Speaker() as speaker:
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
            with Speaker():
                raise _Sentinel("boom")
