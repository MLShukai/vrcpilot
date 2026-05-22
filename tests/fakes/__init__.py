"""Unified test doubles for vrcpilot tests.

Tests must NOT define their own ad-hoc ``_Fake*`` classes for shared
collaborators. Instead, import a fake from this package so the
behaviour and surface are consistent across the suite.

Usage:

    from tests.fakes import FakeCapture, FakePopen

When a fake's surface needs extending, modify the canonical class
here so every test benefits — do not subclass ad-hoc inside a test
file. (Per-test class-level state isolation is provided by helper
fixtures next to each fake; see :mod:`tests.fakes.capture`.)
"""

from __future__ import annotations

from .audio import (
    FakeMic,
    FakeProcessAudioCapture,
    FakePulse,
    FakePulseEventInfo,
    FakePulseModuleInfo,
    FakePulseRegistry,
    FakePwRecordProcess,
    FakeRawPcmStdoutSink,
    FakeSoundDevice,
    FakeSpeaker,
    FakeSpeakerLoop,
    FakeWavSink,
)
from .capture import (
    FakeCapture,
    FakeCaptureLoop,
    FakeMp4Sink,
    FakeWindowsCapture,
    FakeWindowsCaptureControl,
    FakeWindowsFrame,
    FakeY4mStdoutSink,
    make_fresh_windows_capture_subclass,
)
from .inputtino import FakeInputtinoKeyboard, FakeInputtinoMouse, FakeMouseButton
from .ocr import FakeOCREngine
from .osc import FakeUDPClient
from .process import FakePopen, FakeProcess
from .pydirectinput import FakePyDirectInput
from .screenshot import patch_stdin_with_screenshot, write_screenshot_payload
from .x11 import (
    FakePixmap,
    FakePixmapImage,
    FakeXDisplay,
    FakeXGeometry,
    FakeXWindow,
    fake_x11_display_cm,
    make_xerror_subclass,
)

__all__ = [
    "FakeCapture",
    "FakeCaptureLoop",
    "FakeInputtinoKeyboard",
    "FakeInputtinoMouse",
    "FakeMic",
    "FakeMouseButton",
    "FakeMp4Sink",
    "FakeOCREngine",
    "FakePixmap",
    "FakePixmapImage",
    "FakePopen",
    "FakeProcess",
    "FakeProcessAudioCapture",
    "FakePulse",
    "FakePulseEventInfo",
    "FakePulseModuleInfo",
    "FakePulseRegistry",
    "FakePwRecordProcess",
    "FakePyDirectInput",
    "FakeRawPcmStdoutSink",
    "FakeSoundDevice",
    "FakeSpeaker",
    "FakeSpeakerLoop",
    "FakeUDPClient",
    "FakeWavSink",
    "FakeWindowsCapture",
    "FakeWindowsCaptureControl",
    "FakeWindowsFrame",
    "FakeXDisplay",
    "FakeXGeometry",
    "FakeXWindow",
    "FakeY4mStdoutSink",
    "fake_x11_display_cm",
    "make_fresh_windows_capture_subclass",
    "make_xerror_subclass",
    "patch_stdin_with_screenshot",
    "write_screenshot_payload",
]
