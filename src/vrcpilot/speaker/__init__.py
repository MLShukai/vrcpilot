"""Capture VRChat-only application audio (cross-platform via ``proc-tap``).

Public surface:

* :class:`Speaker` -- context-managed session, requires VRChat to be running.
* :class:`SpeakerLoop` -- background-thread driver around :class:`Speaker`.
* :data:`AudioCallback` -- type alias for the chunk callback accepted by
  :class:`SpeakerLoop`.

Linux uses a native PipeWire backend (virtual null-sink + ``pw-link`` +
``pw-record`` subprocess, driven by ``pulsectl`` for the control plane).
Windows and macOS delegate to the cross-platform ``proc-tap`` package
(``ActivateAudioInterfaceAsync`` on Windows, Core Audio on macOS -- the
latter is upstream-experimental). Importing this module does not pull
in any platform-specific dependency by itself.
"""

from __future__ import annotations

from vrcpilot.speaker.loop import AudioCallback, SpeakerLoop
from vrcpilot.speaker.session import Speaker

__all__ = [
    "AudioCallback",
    "Speaker",
    "SpeakerLoop",
]
