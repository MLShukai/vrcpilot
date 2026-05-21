"""Tests for :class:`vrcpilot.speaker.session.Speaker`.

The backend selection is patched in the session's own module
(``vrcpilot.speaker.session._select_speaker_backend``) with the canonical
:class:`tests.helpers.ImplSpeakerBackend` so the wrapper's plumbing
(closed-state, idempotent close, context manager, forwarding) can be
exercised end-to-end without touching the real proc-tap stack.

Following the project rule that ABC wiring tests use a real impl rather
than ``mocker.Mock`` - :class:`ImplSpeakerBackend` is that impl.
"""

from __future__ import annotations

import numpy as np
import pytest
from pytest_mock import MockerFixture

from tests.helpers import ImplSpeakerBackend
from vrcpilot.speaker.base import CHANNELS
from vrcpilot.speaker.session import Speaker


def _patch_backend(
    mocker: MockerFixture,
    backend: ImplSpeakerBackend,
) -> ImplSpeakerBackend:
    """Substitute the backend factory with one that returns ``backend``.

    ``Speaker`` is the unit under test; the platform-backed
    ``SpeakerBackend`` it owns is internal collaboration we replace
    deterministically.
    """
    mocker.patch(
        "vrcpilot.speaker.session._select_speaker_backend",
        return_value=backend,
    )
    return backend


class TestConstruction:
    @pytest.mark.parametrize("bad_timeout", [0.0, -0.1, -1.0])
    def test_rejects_non_positive_read_timeout(
        self,
        mocker: MockerFixture,
        bad_timeout: float,
    ):
        # Validation must happen before the backend factory runs so a
        # misuse never reaches the native capture stack -- the failure
        # should point at the caller, not at proc-tap.
        spy = mocker.patch(
            "vrcpilot.speaker.session._select_speaker_backend",
            return_value=ImplSpeakerBackend(),
        )
        with pytest.raises(ValueError, match="read_timeout must be > 0"):
            Speaker(read_timeout=bad_timeout)
        spy.assert_not_called()

    def test_forwards_kwargs_to_backend_factory(self, mocker: MockerFixture):
        # The whole point of the wrapper is to be a thin shim, so the
        # backend factory must receive exactly the kwargs the caller
        # supplied (no rewriting, no defaults leaking through).
        spy = mocker.patch(
            "vrcpilot.speaker.session._select_speaker_backend",
            return_value=ImplSpeakerBackend(),
        )
        speaker = Speaker(read_timeout=1.5)
        try:
            spy.assert_called_once_with(read_timeout=1.5)
        finally:
            speaker.close()

    def test_uses_documented_defaults(self, mocker: MockerFixture):
        spy = mocker.patch(
            "vrcpilot.speaker.session._select_speaker_backend",
            return_value=ImplSpeakerBackend(),
        )
        speaker = Speaker()
        try:
            spy.assert_called_once_with(read_timeout=2.0)
        finally:
            speaker.close()


class TestRead:
    def test_forwards_backend_buffer(self, mocker: MockerFixture):
        # ``Speaker.read`` is a pass-through: whatever the backend
        # returns is what the caller sees, unmodified.
        payload = np.full((8, CHANNELS), 0.25, dtype=np.float32)
        _patch_backend(mocker, ImplSpeakerBackend(buffer=payload))

        with Speaker() as speaker:
            buf = speaker.read()

        np.testing.assert_array_equal(buf, payload)
        assert buf.dtype == np.float32
        assert buf.shape == (8, CHANNELS)

    def test_read_after_close_raises(self, mocker: MockerFixture):
        _patch_backend(mocker, ImplSpeakerBackend())
        speaker = Speaker()
        speaker.close()
        with pytest.raises(RuntimeError, match="Speaker is closed"):
            speaker.read()


class _CountingBackend(ImplSpeakerBackend):
    """ImplSpeakerBackend that counts close() invocations.

    Defined in the test file because the count is only useful for the
    wrapper's idempotency tests; pushing it into ``tests/helpers`` would
    pollute the shared fake with state that no other suite needs.
    """

    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        super().close()


class TestClose:
    def test_close_is_idempotent(self, mocker: MockerFixture):
        backend = _CountingBackend()
        _patch_backend(mocker, backend)

        speaker = Speaker()
        speaker.close()
        speaker.close()
        speaker.close()

        # Backend.close runs only on the first Speaker.close call.
        assert backend.close_calls == 1

    def test_context_manager_closes(self, mocker: MockerFixture):
        backend = _CountingBackend()
        _patch_backend(mocker, backend)

        with Speaker() as speaker:
            pass

        assert backend.close_calls == 1
        with pytest.raises(RuntimeError, match="Speaker is closed"):
            speaker.read()

    def test_exit_does_not_suppress_exception(self, mocker: MockerFixture):
        # The context manager must propagate exceptions raised inside
        # the ``with`` block. Suppression would silently swallow real
        # failures.
        _patch_backend(mocker, ImplSpeakerBackend())

        class _Sentinel(Exception):
            pass

        with pytest.raises(_Sentinel):
            with Speaker():
                raise _Sentinel("boom")
