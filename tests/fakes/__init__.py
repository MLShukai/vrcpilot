"""Unified test doubles for vrcpilot tests.

Tests must NOT define their own ad-hoc ``_Fake*`` classes for shared
collaborators. Instead, import a fake from this package so the
behaviour and surface are consistent across the suite.

Per the testing policy (``.claude/skills/vrcpilot-testing/SKILL.md``),
this package only re-exports fakes that stand in for **vrcpilot's own
ABCs** -- 3rd-party library surfaces must never be faked here; tests
that need them belong in the integration-real tier (real PipeWire,
real Xvfb, real subprocess, loopback UDP, etc.).
"""

from __future__ import annotations

from .audio import FakeMic, FakeSpeaker, FakeSpeakerLoop
from .capture import FakeCapture, FakeCaptureLoop
from .detect import FakeDetectEngine
from .ocr import FakeOCREngine
from .record_muxer import FakeMkvStdoutMuxer, FakeMp4FileMuxer, FakeWavFileMuxer
from .screenshot import patch_stdin_with_screenshot, write_screenshot_payload

__all__ = [
    "FakeCapture",
    "FakeCaptureLoop",
    "FakeDetectEngine",
    "FakeMic",
    "FakeMkvStdoutMuxer",
    "FakeMp4FileMuxer",
    "FakeOCREngine",
    "FakeSpeaker",
    "FakeSpeakerLoop",
    "FakeWavFileMuxer",
    "patch_stdin_with_screenshot",
    "write_screenshot_payload",
]
