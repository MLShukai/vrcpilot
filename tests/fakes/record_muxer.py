"""Test doubles for the CLI-internal record muxers.

Stand-ins for :class:`vrcpilot.cli.record.muxer.Mp4FileMuxer`,
:class:`vrcpilot.cli.record.muxer.WavFileMuxer`, and
:class:`vrcpilot.cli.record.muxer.MkvStdoutMuxer`. Mirrors the
``BaseMuxer`` surface (``write_video`` / ``write_audio`` /
``frame_count`` / ``sample_count`` / ``close`` plus the context-manager
protocol) so ``vrcpilot.cli.record`` integration tests can run without
invoking PyAV.

Each fake exposes a class-level ``instances`` list so tests can assert
how many muxers were constructed and inspect their constructor args.
Reset between tests via the ``record_fakes``-style fixture in the local
conftest (``cls.reset()`` clears the list in place).
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self, override

import numpy as np
from numpy.typing import NDArray

from vrcpilot.cli.record.muxer import BaseMuxer


class FakeMp4FileMuxer(BaseMuxer):
    """Stand-in for :class:`vrcpilot.cli.record.muxer.Mp4FileMuxer`.

    Records every ``write_video`` / ``write_audio`` invocation in
    :attr:`writes_video` / :attr:`writes_audio` so CLI integration
    tests can assert what would have been encoded without invoking
    PyAV.
    """

    instances: list[FakeMp4FileMuxer] = []

    def __init__(
        self,
        output_path: Path,
        *,
        fps: float,
        video: bool,
        audio: bool,
    ) -> None:
        self.output_path = output_path
        self.fps = fps
        self.video = video
        self.audio = audio
        self.writes_video: list[NDArray[np.uint8]] = []
        self.writes_audio: list[NDArray[np.float32]] = []
        self.closed = False
        FakeMp4FileMuxer.instances.append(self)

    @override
    def write_video(self, frame_rgb: NDArray[np.uint8]) -> None:
        self.writes_video.append(frame_rgb)

    @override
    def write_audio(self, chunk_pcm: NDArray[np.float32]) -> None:
        self.writes_audio.append(chunk_pcm)

    @property
    @override
    def frame_count(self) -> int:
        return len(self.writes_video)

    @property
    @override
    def sample_count(self) -> int:
        return sum(int(chunk.shape[0]) for chunk in self.writes_audio)

    @override
    def close(self) -> None:
        self.closed = True

    @override
    def __enter__(self) -> Self:
        return self

    @override
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()

    @classmethod
    def reset(cls) -> None:
        """Clear :attr:`instances` in place between tests."""
        cls.instances.clear()


class FakeWavFileMuxer(BaseMuxer):
    """Stand-in for :class:`vrcpilot.cli.record.muxer.WavFileMuxer`.

    Audio-only fake: :meth:`write_video` raises just like the real
    class so misuse is caught in tests too.
    """

    instances: list[FakeWavFileMuxer] = []

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.writes_audio: list[NDArray[np.float32]] = []
        self.closed = False
        FakeWavFileMuxer.instances.append(self)

    @override
    def write_video(self, frame_rgb: NDArray[np.uint8]) -> None:
        del frame_rgb
        raise RuntimeError("FakeWavFileMuxer does not accept video frames")

    @override
    def write_audio(self, chunk_pcm: NDArray[np.float32]) -> None:
        self.writes_audio.append(chunk_pcm)

    @property
    @override
    def frame_count(self) -> int:
        return 0

    @property
    @override
    def sample_count(self) -> int:
        return sum(int(chunk.shape[0]) for chunk in self.writes_audio)

    @override
    def close(self) -> None:
        self.closed = True

    @override
    def __enter__(self) -> Self:
        return self

    @override
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()

    @classmethod
    def reset(cls) -> None:
        """Clear :attr:`instances` in place between tests."""
        cls.instances.clear()


class FakeMkvStdoutMuxer(BaseMuxer):
    """Stand-in for :class:`vrcpilot.cli.record.muxer.MkvStdoutMuxer`.

    Same constructor shape as the real class so CLI tests can swap it
    in via ``mocker.patch``. The optional ``stream`` keyword is
    accepted for signature parity but ignored — the fake never writes
    bytes.
    """

    instances: list[FakeMkvStdoutMuxer] = []

    def __init__(
        self,
        *,
        fps: float,
        video: bool,
        audio: bool,
        stream: BinaryIO | None = None,
    ) -> None:
        self.fps = fps
        self.video = video
        self.audio = audio
        self.stream = stream
        self.writes_video: list[NDArray[np.uint8]] = []
        self.writes_audio: list[NDArray[np.float32]] = []
        self.closed = False
        FakeMkvStdoutMuxer.instances.append(self)

    @override
    def write_video(self, frame_rgb: NDArray[np.uint8]) -> None:
        self.writes_video.append(frame_rgb)

    @override
    def write_audio(self, chunk_pcm: NDArray[np.float32]) -> None:
        self.writes_audio.append(chunk_pcm)

    @property
    @override
    def frame_count(self) -> int:
        return len(self.writes_video)

    @property
    @override
    def sample_count(self) -> int:
        return sum(int(chunk.shape[0]) for chunk in self.writes_audio)

    @override
    def close(self) -> None:
        self.closed = True

    @override
    def __enter__(self) -> Self:
        return self

    @override
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()

    @classmethod
    def reset(cls) -> None:
        """Clear :attr:`instances` in place between tests."""
        cls.instances.clear()
