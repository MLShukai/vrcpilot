"""Platform-agnostic tests for :class:`vrcpilot.mic.Mic`.

Only validation that fires **before** any device-resolution work lives
here; everything that actually opens a soundcard player needs a real
PulseAudio / WASAPI session and so belongs in the platform-split
``test_session_linux.py`` / ``test_session_windows.py`` files (the
latter to be added when a Windows runner exists).
"""

from __future__ import annotations

import pytest

from vrcpilot.mic import Mic


class TestArgumentValidation:
    """``Mic`` rejects bad ``sample_rate`` / ``channels`` before any I/O."""

    @pytest.mark.parametrize("bad", [0, -1, -48000])
    def test_non_positive_sample_rate_rejected(self, bad: int) -> None:
        # Validation must fire before resolve_device_name / lookup_speaker
        # so the caller sees a clear ValueError instead of a downstream
        # libpulse / WASAPI complaint about an invalid format.
        with pytest.raises(ValueError, match="sample_rate"):
            Mic(sample_rate=bad)

    @pytest.mark.parametrize("bad", [0, -1, -2])
    def test_non_positive_channels_rejected(self, bad: int) -> None:
        with pytest.raises(ValueError, match="channels"):
            Mic(channels=bad)
