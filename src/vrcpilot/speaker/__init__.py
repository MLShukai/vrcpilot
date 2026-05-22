"""Capture VRChat-only application audio (Linux / Windows).

Platform-specific backends live in :mod:`vrcpilot.speaker.linux`
(native PipeWire) and :mod:`vrcpilot.speaker.windows` (``proc-tap``);
they are imported lazily so importing this package never drags in the
other platform's dependencies.
"""

from __future__ import annotations

from vrcpilot.speaker.loop import AudioCallback, SpeakerLoop
from vrcpilot.speaker.session import Speaker

__all__ = [
    "AudioCallback",
    "Speaker",
    "SpeakerLoop",
]
