"""Capture-related test doubles.

Stand-ins for the public :class:`vrcpilot.Capture` and
:class:`vrcpilot.CaptureLoop`, and the third-party
``windows_capture.WindowsCapture`` library.

All stay duck-type compatible with the real surfaces so production
code can be patched in place via ``mocker.patch`` and treat the fake
as if it were the original.
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
    can be substituted via either ``mocker.patch(..., FakeCapture)``
    (replace the class) or ``mocker.patch(..., return_value=fake)``
    (replace the instance).

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
    before construction. Reset between tests by the
    ``capture_fakes``-style fixture in your local conftest.
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
    ) -> None:
        if FakeCaptureLoop.init_side_effect is not None:
            raise FakeCaptureLoop.init_side_effect
        self.callback = callback
        self.fps = fps
        self.frame_timeout = frame_timeout
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


class FakeWindowsCaptureControl:
    """Stand-in for ``windows_capture.CaptureControl``.

    Records ``stop()`` invocations and optionally raises so close
    handshake error paths can be exercised.
    """

    def __init__(self) -> None:
        self.stop_calls: int = 0
        self.stop_raises: BaseException | None = None

    def stop(self) -> None:
        self.stop_calls += 1
        if self.stop_raises is not None:
            raise self.stop_raises


class _FakeFrameBuffer:
    """Mimic ``windows_capture.Frame.frame_buffer.tobytes()``."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def tobytes(self) -> bytes:
        return self._payload


class FakeWindowsFrame:
    """Stand-in for ``windows_capture.Frame``.

    Only exposes ``frame_buffer`` / ``width`` / ``height`` because
    those are the sole fields :class:`vrcpilot.capture.windows.Win32CaptureBackend`
    reads.
    """

    def __init__(self, payload: bytes, width: int, height: int) -> None:
        self.frame_buffer = _FakeFrameBuffer(payload)
        self.width = width
        self.height = height


class FakeWindowsCapture:
    """Stand-in for ``windows_capture.WindowsCapture``.

    Captures the constructor kwargs on the class, records the
    ``@event``-decorated handlers, and exposes :meth:`emit_frame` so
    each test can fire frames synchronously into the registered
    ``on_frame_arrived`` callback. Unlike the real library, no
    background thread is spawned — the test owns timing.

    Subclass per test (in a fixture) so each test gets fresh
    class-level state. Tests sharing the canonical class would leak
    ``last_kwargs`` / ``start_raises`` / ``last_instance`` between
    runs. See ``capture_fakes``-style fixtures in the test packages.
    """

    last_kwargs: dict[str, object] = {}
    start_raises: BaseException | None = None
    last_instance: FakeWindowsCapture | None = None

    def __init__(self, **kwargs: object) -> None:
        type(self).last_kwargs = kwargs
        type(self).last_instance = self
        self._frame_handler: object = None
        self._closed_handler: object = None
        self._control = FakeWindowsCaptureControl()

    def event(self, fn: object) -> object:
        """Replicate ``windows_capture.WindowsCapture.event``.

        Real library routes by ``__name__`` and returns the function
        untouched so the decorator preserves the original definition.
        """
        name = getattr(fn, "__name__", "")
        if name == "on_frame_arrived":
            self._frame_handler = fn
        elif name == "on_closed":
            self._closed_handler = fn
        return fn

    def start_free_threaded(self) -> FakeWindowsCaptureControl:
        start_raises = type(self).start_raises
        if start_raises is not None:
            raise start_raises
        return self._control

    def emit_frame(self, payload: bytes, width: int, height: int) -> None:
        """Synchronously invoke the registered ``on_frame_arrived``.

        The real library passes a ``Frame`` plus an
        ``InternalCaptureControl``; the production code only reads
        ``frame_buffer`` / ``width`` / ``height`` and ignores the
        control, so a plain ``object()`` stand-in suffices.
        """
        handler = self._frame_handler
        assert handler is not None, "on_frame_arrived was not registered"
        handler(FakeWindowsFrame(payload, width, height), object())  # type: ignore[operator]

    @property
    def control(self) -> FakeWindowsCaptureControl:
        return self._control


def make_fresh_windows_capture_subclass() -> type[FakeWindowsCapture]:
    """Return a subclass of :class:`FakeWindowsCapture` with isolated state.

    Each test that exercises the WGC backend needs its own
    ``last_kwargs`` / ``start_raises`` / ``last_instance`` so class-
    level mutations do not leak between tests. Centralising the
    subclass dance here keeps test files free of the boilerplate that
    the strategy document forbids.
    """

    class _Fresh(FakeWindowsCapture):
        last_kwargs: dict[str, object] = {}
        start_raises: BaseException | None = None
        last_instance: FakeWindowsCapture | None = None

    return _Fresh
