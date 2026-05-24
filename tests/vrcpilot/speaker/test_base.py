"""Tests for the :class:`SpeakerBackend` ABC and format constants.

Only the cross-module invariants the rest of the speaker stack relies
on are verified here. Trivia (``SAMPLE_RATE == 48000``, ABC raising
``TypeError`` for missing abstract methods, etc.) is left to Python's
type system / ABC machinery -- those tests have zero marginal value.
"""

from __future__ import annotations

import numpy as np

from tests.helpers import ImplSpeakerBackend
from vrcpilot.speaker.base import CHANNELS, DTYPE, SAMPLE_RATE


class TestFormatConstants:
    def test_dtype_is_float32_used_by_concrete_backends(self) -> None:
        # Both production backends (``ProcTapSpeakerBackend`` and
        # ``PipeWireSpeakerBackend``) treat the ``DTYPE`` constant as
        # the load-bearing pin: arrays they hand to consumers carry
        # exactly this dtype. If DTYPE drifted to e.g. float64,
        # ``np.frombuffer(..., dtype=DTYPE)`` inside the backends would
        # silently mis-frame every read.
        assert DTYPE is np.float32

    def test_sample_rate_and_channels_match_the_mic_modality(self) -> None:
        # The mic modality opens its libpulse / WASAPI player at the
        # same rate so the loopback chain never has to resample. If the
        # constants drift apart the speaker -> mic relay (a documented
        # use case) silently gets a clock mismatch.
        from vrcpilot.mic.base import SAMPLE_RATE as MIC_SAMPLE_RATE

        assert SAMPLE_RATE == MIC_SAMPLE_RATE
        # Two stereo channels is the documented contract -- not a
        # typo for 1 (mono) or 6 (5.1) -- and consumers index
        # ``arr[:, 0]`` / ``arr[:, 1]`` directly.
        assert CHANNELS == 2


class TestSpeakerBackendContract:
    def test_read_returns_documented_shape_and_dtype(self) -> None:
        # The ABC's docstring promises shape ``(N, CHANNELS)`` with
        # float32 dtype. Consumers ``reshape(-1, CHANNELS)`` against
        # this guarantee, so a regression where the impl returns a 1-D
        # array would crash downstream sinks.
        payload = np.ones((4, CHANNELS), dtype=np.float32)
        backend = ImplSpeakerBackend(buffer=payload)
        try:
            buf = backend.read()
        finally:
            backend.close()
        assert buf.dtype == np.float32
        assert buf.ndim == 2
        assert buf.shape == (4, CHANNELS)

    def test_close_is_idempotent(self) -> None:
        # The ABC documents idempotence: ``ExitStack`` rollback paths
        # and ``__exit__`` chains will call close twice on a backend
        # that already saw its first close at the producer side.
        backend = ImplSpeakerBackend()
        backend.close()
        backend.close()
