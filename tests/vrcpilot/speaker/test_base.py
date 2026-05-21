"""Unit tests for the speaker backend ABC and format constants."""

from __future__ import annotations

import numpy as np
import pytest

from tests.helpers import ImplSpeakerBackend
from vrcpilot.speaker.base import CHANNELS, DTYPE, SAMPLE_RATE, SpeakerBackend


class TestFormatConstants:
    def test_sample_rate(self):
        assert SAMPLE_RATE == 48000

    def test_channels(self):
        assert CHANNELS == 2

    def test_dtype(self):
        # ``DTYPE`` is documented as the element dtype of arrays
        # returned by :meth:`SpeakerBackend.read`; pin it to
        # ``np.float32`` so downstream consumers can rely on the
        # identity check.
        assert DTYPE is np.float32


class TestSpeakerBackendABC:
    def test_backend_cannot_be_instantiated_directly(self):
        # ``SpeakerBackend`` is an ABC: instantiating it raises
        # ``TypeError`` because ``read`` / ``close`` are still abstract.
        with pytest.raises(TypeError):
            SpeakerBackend()  # pyright: ignore[reportAbstractUsage]

    def test_backend_subclass_missing_read_cannot_instantiate(self):
        class _MissingRead(SpeakerBackend):
            def close(self) -> None:
                pass

        with pytest.raises(TypeError):
            _MissingRead()  # pyright: ignore[reportAbstractUsage]

    def test_backend_subclass_missing_close_cannot_instantiate(self):
        class _MissingClose(SpeakerBackend):
            def read(self):  # pyright: ignore[reportMissingParameterType]
                return np.zeros((0, CHANNELS), dtype=np.float32)

        with pytest.raises(TypeError):
            _MissingClose()  # pyright: ignore[reportAbstractUsage]


class TestSpeakerBackendReadContract:
    def test_read_returns_documented_shape_and_dtype(self):
        # The ABC documents shape ``(N, CHANNELS)`` and dtype
        # ``float32``; verify a concrete impl can satisfy that.
        backend = ImplSpeakerBackend()
        buf = backend.read()
        assert buf.dtype == np.float32
        assert buf.ndim == 2
        assert buf.shape[1] == CHANNELS

    def test_read_forwards_buffer_to_caller(self):
        # Sanity check that the ABC does not transform the returned
        # array: whatever the backend produces is what the caller sees.
        payload = np.ones((4, CHANNELS), dtype=np.float32)
        backend = ImplSpeakerBackend(buffer=payload)
        assert backend.read() is payload


class TestSpeakerBackendCloseContract:
    def test_close_is_idempotent(self):
        # The ABC requires ``close`` to be idempotent: repeated calls
        # must not raise. Internal call counting belongs to the impl,
        # not to the contract, so we only verify the no-raise guarantee.
        backend = ImplSpeakerBackend()
        backend.close()
        backend.close()
