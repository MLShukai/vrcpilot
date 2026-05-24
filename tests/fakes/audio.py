"""Audio-related test doubles.

Stand-ins mirroring vrcpilot-owned audio ABCs (per the testing
policy, ``.claude/skills/vrcpilot-testing/SKILL.md``). 3rd-party
library surfaces (``pulsectl``, ``soundcard``, ``proctap``,
``pw-record`` via ``subprocess.Popen``) are NOT faked here -- tests
that need them belong in the integration-real tier (real PipeWire
null-sink, real soundcard, real proctap on Windows runners).

* :class:`FakeSpeaker` mirrors the public
  :class:`vrcpilot.speaker.session.Speaker` surface (``read`` / ``close``
  / context manager). Used by :class:`vrcpilot.speaker.loop.SpeakerLoop`
  tests where the loop's threading machinery is exercised against a
  deterministic chunk source.

* :class:`FakeSpeakerLoop` mirrors the CLI-facing
  :class:`vrcpilot.speaker.SpeakerLoop` so ``vrcpilot.cli.record``
  tests can run without proc-tap. Mirrors :mod:`tests.fakes.capture`
  1:1 (``instances`` class-level list, ``frames_per_start`` /
  ``init_side_effect`` knobs).

* :class:`FakeMic` is the CLI-side stand-in for
  :class:`vrcpilot.mic.Mic` for ``vrcpilot.cli.mic`` tests.

The fakes only implement methods production actually calls; the
``feedback_fakes_mirror_production`` rule in the project memory
applies.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from types import TracebackType
from typing import Self

import numpy as np
from numpy.typing import NDArray

from vrcpilot.speaker.base import CHANNELS


class FakeSpeaker:
    """Stand-in for :class:`vrcpilot.speaker.session.Speaker`.

    Used in :class:`vrcpilot.speaker.loop.SpeakerLoop` tests where the
    OS-level proc-tap backend is irrelevant but the loop's own threading
    machinery still needs to be exercised against a real, deterministic
    chunk source.

    Constructor arguments mirror :class:`vrcpilot.Speaker` so the fake
    can be substituted via either ``mocker.patch(..., FakeSpeaker)``
    (replace the class) or ``mocker.patch(..., return_value=fake)``
    (replace the instance).

    Args:
        read_timeout: Accepted for signature compatibility; recorded as
            :attr:`read_timeout` so tests can assert forwarding.
        read_side_effect: Raised from :meth:`read` instead of returning
            a chunk. ``None`` (default) returns a zero-length chunk.
        read_delay: Sleep injected before each :meth:`read` returns,
            useful for pacing tests.
        chunk: ndarray returned from :meth:`read`. Default is an empty
            ``(0, CHANNELS)`` array so tests can assert empty-chunk
            forwarding without setting anything up.
    """

    def __init__(
        self,
        *,
        read_timeout: float = 2.0,
        read_side_effect: BaseException | None = None,
        read_delay: float = 0.0,
        chunk: NDArray[np.float32] | None = None,
    ) -> None:
        self.read_timeout = read_timeout
        self.read_calls: int = 0
        self.close_calls: int = 0
        self._read_side_effect = read_side_effect
        self._read_delay = read_delay
        self._chunk = (
            chunk if chunk is not None else np.zeros((0, CHANNELS), dtype=np.float32)
        )

    def read(self) -> NDArray[np.float32]:
        self.read_calls += 1
        if self._read_delay > 0:
            time.sleep(self._read_delay)
        if self._read_side_effect is not None:
            raise self._read_side_effect
        return self._chunk

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


class FakeSpeakerLoop:
    """Stand-in for :class:`vrcpilot.speaker.SpeakerLoop`.

    Replaces the real loop in CLI tests where exercising the worker
    thread is not the point. ``start()`` synchronously emits a fixed
    number of chunks into the user callback so end-to-end behaviour
    of consumers (sinks, signal handlers) can still be verified.

    Class-level state (:attr:`instances` / :attr:`frames_per_start` /
    :attr:`samples_per_frame` / :attr:`init_side_effect`) is mutable
    so tests can configure behaviour before construction. Reset
    between tests by the ``record_fakes``-style fixture in your local
    conftest.
    """

    instances: list[FakeSpeakerLoop] = []
    frames_per_start: int = 3
    samples_per_frame: int = 1024
    init_side_effect: BaseException | None = None

    def __init__(
        self,
        callback: Callable[[NDArray[np.float32]], None],
        *,
        chunk_seconds: float = 0.05,
        read_timeout: float = 2.0,
        pid: int | None = None,
    ) -> None:
        if FakeSpeakerLoop.init_side_effect is not None:
            raise FakeSpeakerLoop.init_side_effect
        self.callback = callback
        self.chunk_seconds = chunk_seconds
        self.read_timeout = read_timeout
        self.pid = pid
        self.start_calls = 0
        FakeSpeakerLoop.instances.append(self)

    def start(self) -> None:
        self.start_calls += 1
        chunk = np.zeros(
            (FakeSpeakerLoop.samples_per_frame, CHANNELS), dtype=np.float32
        )
        for _ in range(FakeSpeakerLoop.frames_per_start):
            self.callback(chunk)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb


class FakeMic:
    """Stand-in for :class:`vrcpilot.mic.Mic` in CLI tests.

    Mirrors the constructor-opens-stream / single-chunk-play /
    explicit-close lifecycle plus the public ``device_name`` /
    ``device_id`` / ``sample_rate`` / ``channels`` properties so CLI
    integration tests can assert the right format was chosen, every
    chunk was forwarded, and the session was released on the way out.
    Construction never raises; the device-not-found path is exercised
    by patching ``Mic`` to raise on instantiation instead.
    """

    instances: list[FakeMic] = []

    def __init__(
        self,
        device: str | None = None,
        *,
        sample_rate: int = 48000,
        channels: int = 1,
    ) -> None:
        self.device_argument = device
        self._sample_rate = sample_rate
        self._channels = channels
        self.played: list[NDArray[np.float32]] = []
        self.closed: bool = False
        FakeMic.instances.append(self)

    @property
    def device_name(self) -> str:
        return self.device_argument or "fake-device"

    @property
    def device_id(self) -> str:
        return f"fake.{self.device_argument or 'default'}"

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def play(self, chunk: NDArray[np.float32]) -> None:
        if self.closed:
            raise RuntimeError("Mic is closed")
        self.played.append(chunk)

    def close(self) -> None:
        self.closed = True

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
