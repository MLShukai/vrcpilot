"""Capture-related test doubles.

Stand-ins for the in-house :class:`vrcpilot.Capture` and
:class:`vrcpilot.CaptureLoop` abstractions. Only the surface that
production code actually invokes is mirrored.

These are *own-ABC* fakes (the abstractions belong to vrcpilot itself),
which is the only category the test strategy still permits in
``tests/fakes/``. Third-party library surfaces (e.g. the upstream
``windows_capture.WindowsCapture``) are deliberately not mirrored here
— their behaviour is covered by ``integration-real`` tests against the
real library on a Windows runner.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from types import TracebackType
from typing import Self

import numpy as np


class FakeCapture:
    """Stand-in for :class:`vrcpilot.Capture`.

    Used in :class:`vrcpilot.CaptureLoop` tests where the OS-level
    backend is irrelevant but the loop's own threading machinery still
    needs to be exercised against a real, deterministic frame source.

    Constructor arguments mirror :class:`vrcpilot.Capture` so the fake
    can be substituted via ``mocker.patch(..., return_value=fake)``.

    Args:
        frame_timeout: Accepted for signature compatibility; ignored.
        read_side_effect: Raised from :meth:`read` instead of returning
            a frame. ``None`` (default) returns a zero ndarray.
        read_delay: Sleep injected before each :meth:`read` returns,
            useful for FPS-pacing tests.
    """

    def __init__(
        self,
        *,
        frame_timeout: float = 2.0,
        read_side_effect: BaseException | None = None,
        read_delay: float = 0.0,
    ) -> None:
        del frame_timeout
        self.read_calls: int = 0
        self.close_calls: int = 0
        self._read_side_effect = read_side_effect
        self._read_delay = read_delay

    def read(self) -> np.ndarray:
        self.read_calls += 1
        if self._read_delay > 0:
            time.sleep(self._read_delay)
        if self._read_side_effect is not None:
            raise self._read_side_effect
        return np.zeros((4, 4, 3), dtype=np.uint8)

    def close(self) -> None:
        self.close_calls += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()


class FakeCaptureLoop:
    """Stand-in for :class:`vrcpilot.CaptureLoop`.

    Replaces the real loop in CLI tests where exercising the worker
    thread is not the point. ``start()`` synchronously emits a fixed
    number of frames into the user callback so end-to-end behaviour
    of consumers (sinks, signal handlers) can still be verified.

    Class-level state (``instances`` / ``frames_per_start`` /
    ``init_side_effect``) is mutable so tests can configure behaviour
    before construction. Reset between tests by a fixture in your
    local conftest.
    """

    instances: list[FakeCaptureLoop] = []
    frames_per_start: int = 3
    init_side_effect: BaseException | None = None

    def __init__(
        self,
        callback: Callable[[np.ndarray], None],
        *,
        fps: float,
        frame_timeout: float = 2.0,
        pid: int | None = None,
    ) -> None:
        if FakeCaptureLoop.init_side_effect is not None:
            raise FakeCaptureLoop.init_side_effect
        self.callback = callback
        self.fps = fps
        self.frame_timeout = frame_timeout
        self.pid = pid
        self.start_calls = 0
        FakeCaptureLoop.instances.append(self)

    def start(self) -> None:
        self.start_calls += 1
        for _ in range(FakeCaptureLoop.frames_per_start):
            self.callback(np.zeros((4, 4, 3), dtype=np.uint8))

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
