"""Tests for :mod:`vrcpilot.cli.mic`."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from pytest_mock import MockerFixture

from tests.fakes import FakeMic
from vrcpilot.cli import main
from vrcpilot.mic import MicDeviceNotFoundError


@pytest.fixture(autouse=True)
def _reset_fake_mic_instances() -> None:
    """Clear cross-test state on the canonical FakeMic mirror.

    ``FakeMic.instances`` is class-level so a previous test's invocation
    would leak into the current test's ``instances[0]`` lookup.
    """
    FakeMic.instances = []


@pytest.fixture
def fake_mic(mocker: MockerFixture) -> type[FakeMic]:
    """Patch ``vrcpilot.cli.mic.Mic`` to the canonical fake.

    Tests assert against ``FakeMic.instances`` to inspect played chunks
    and the device argument the CLI forwarded.
    """
    mocker.patch("vrcpilot.cli.mic.Mic", FakeMic)
    return FakeMic


def _write_wav(
    path: Path, samples: NDArray[np.int16], *, channels: int, rate: int
) -> None:
    """Write ``samples`` as a 16-bit PCM WAV at ``path``."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())


def _build_wav_bytes(samples: NDArray[np.int16], *, channels: int, rate: int) -> bytes:
    """Return WAV-formatted bytes for ``samples``."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


class _FakeStdin:
    """Minimal stand-in for ``sys.stdin`` supporting ``isatty()`` and
    ``.buffer.read``."""

    def __init__(self, payload: bytes, *, isatty: bool = False) -> None:
        self.buffer = io.BytesIO(payload)
        self._isatty = isatty

    def isatty(self) -> bool:
        return self._isatty


class TestArgParsing:
    def test_no_input_on_tty_returns_exit_2(
        self,
        fake_mic: type[FakeMic],
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_mic
        # Simulate an interactive stdin so the default ``-i -`` is refused.
        mocker.patch("vrcpilot.cli.mic.sys.stdin", new=_FakeStdin(b"", isatty=True))

        exit_code = main(["mic"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "no audio piped to stdin" in captured.err
        assert FakeMic.instances == []
        assert captured.out == ""

    def test_auto_format_with_non_wav_path_returns_exit_2(
        self,
        fake_mic: type[FakeMic],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_mic
        raw = tmp_path / "audio.raw"
        raw.write_bytes(b"\x00\x00\x00\x00")

        exit_code = main(["mic", "-i", str(raw)])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "cannot auto-detect format" in captured.err
        # Mic must not be constructed when the parser bails early.
        assert FakeMic.instances == []


class TestWavFileInput:
    def test_stereo_wav_file_decodes_and_plays(
        self,
        fake_mic: type[FakeMic],
        tmp_path: Path,
    ):
        # Two-frame stereo WAV at 24 kHz: pin ``--rate`` is *ignored* for WAV.
        samples = np.array([[0, 1000], [-1000, 0]], dtype=np.int16)
        wav_path = tmp_path / "stereo.wav"
        _write_wav(wav_path, samples, channels=2, rate=24000)

        # --rate intentionally wrong on purpose: WAV path must use the
        # framerate from the file header, not the flag.
        exit_code = main(["mic", "-i", str(wav_path), "--rate", "8000"])

        assert exit_code == 0
        assert len(fake_mic.instances) == 1
        chunks, sample_rate = fake_mic.instances[0].played[0]
        assert sample_rate == 24000
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.dtype == np.float32
        assert chunk.shape == (2, 2)
        # Values are int16 -> float32 / 32768.0.
        assert chunk[0, 1] == pytest.approx(1000 / 32768.0)
        assert chunk[1, 0] == pytest.approx(-1000 / 32768.0)

    def test_mono_wav_file_is_1d(
        self,
        fake_mic: type[FakeMic],
        tmp_path: Path,
    ):
        samples = np.array([0, 500, -500, 0], dtype=np.int16)
        wav_path = tmp_path / "mono.wav"
        _write_wav(wav_path, samples, channels=1, rate=16000)

        exit_code = main(["mic", "-i", str(wav_path)])

        assert exit_code == 0
        chunks, sample_rate = fake_mic.instances[0].played[0]
        assert sample_rate == 16000
        chunk = chunks[0]
        # Mono WAV must arrive as a flat (N,) array so Mic.play infers 1 channel.
        assert chunk.ndim == 1
        assert chunk.shape == (4,)

    def test_int16_min_maps_to_minus_one_exactly(
        self,
        fake_mic: type[FakeMic],
        tmp_path: Path,
    ):
        # Pin the -32768 / 32768.0 = -1.0 boundary the spec calls out.
        samples = np.array(
            [[np.iinfo(np.int16).min, np.iinfo(np.int16).max]], dtype=np.int16
        )
        wav_path = tmp_path / "boundary.wav"
        _write_wav(wav_path, samples, channels=2, rate=48000)

        exit_code = main(["mic", "-i", str(wav_path)])

        assert exit_code == 0
        chunk = fake_mic.instances[0].played[0][0][0]
        # int16 min divided by 32768.0 is exactly -1.0 in float32.
        assert chunk[0, 0] == np.float32(-1.0)
        # Positive max is asymmetric (32767/32768) so it sits just below 1.
        assert chunk[0, 1] < np.float32(1.0)

    def test_wav_with_unsupported_sampwidth_returns_1(
        self,
        fake_mic: type[FakeMic],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_mic
        # Hand-craft an 8-bit WAV (sampwidth=1) which mic should refuse.
        wav_path = tmp_path / "8bit.wav"
        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(8000)
            w.writeframes(b"\x80\x80\x80")

        exit_code = main(["mic", "-i", str(wav_path)])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "16-bit signed PCM" in captured.err

    def test_explicit_format_wav_on_non_wav_extension(
        self,
        fake_mic: type[FakeMic],
        tmp_path: Path,
    ):
        # --format wav overrides extension sniffing.
        samples = np.array([[0, 0]], dtype=np.int16)
        path = tmp_path / "audio.bin"
        _write_wav(path, samples, channels=2, rate=48000)

        exit_code = main(["mic", "-i", str(path), "--format", "wav"])

        assert exit_code == 0
        chunks, rate = fake_mic.instances[0].played[0]
        assert rate == 48000
        assert chunks[0].shape == (1, 2)


class TestRawFileInput:
    def test_s16le_file_chunked_into_generator(
        self,
        fake_mic: type[FakeMic],
        tmp_path: Path,
    ):
        # 480 stereo frames @ 48 kHz = 10 ms; --chunk-ms 5 should split
        # into two 5-ms chunks (240 frames each).
        frame_count = 480
        samples = np.arange(frame_count * 2, dtype=np.int16).reshape(-1, 2)
        raw_path = tmp_path / "audio.raw"
        raw_path.write_bytes(samples.tobytes())

        exit_code = main(
            [
                "mic",
                "-i",
                str(raw_path),
                "--format",
                "s16le",
                "--rate",
                "48000",
                "--channels",
                "2",
                "--chunk-ms",
                "5",
            ]
        )

        assert exit_code == 0
        chunks, rate = fake_mic.instances[0].played[0]
        assert rate == 48000
        # 480 frames split into 240-frame chunks → 2 yields.
        assert len(chunks) == 2
        assert chunks[0].shape == (240, 2)
        assert chunks[1].shape == (240, 2)
        # Concatenating should reproduce the original int16 payload.
        joined = np.concatenate(chunks, axis=0)
        np.testing.assert_allclose(joined, samples.astype(np.float32) / 32768.0)

    def test_s16le_mono_file(
        self,
        fake_mic: type[FakeMic],
        tmp_path: Path,
    ):
        samples = np.arange(100, dtype=np.int16)
        raw_path = tmp_path / "mono.raw"
        raw_path.write_bytes(samples.tobytes())

        exit_code = main(
            [
                "mic",
                "-i",
                str(raw_path),
                "--format",
                "s16le",
                "--channels",
                "1",
                "--rate",
                "16000",
                "--chunk-ms",
                "100",
            ]
        )

        assert exit_code == 0
        chunks, rate = fake_mic.instances[0].played[0]
        assert rate == 16000
        # Mono raw stays 1-D so Mic.play infers mono.
        assert chunks[0].ndim == 1

    def test_missing_file_returns_1(
        self,
        fake_mic: type[FakeMic],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        missing = tmp_path / "nope.wav"

        exit_code = main(["mic", "-i", str(missing)])

        assert exit_code == 1
        captured = capsys.readouterr()
        # Either FileNotFoundError or wave.Error message -- both
        # funnel through the ``vrcpilot:`` prefix.
        assert "vrcpilot:" in captured.err
        assert fake_mic.instances == [] or fake_mic.instances[0].played == []


class TestStdinInput:
    def test_stdin_s16le_default_format(
        self,
        fake_mic: type[FakeMic],
        mocker: MockerFixture,
    ):
        # 96 stereo frames = 1 ms @ 48000; chunk-ms 1 → 1 chunk of 48 frames.
        frame_count = 48
        samples = np.arange(frame_count * 2, dtype=np.int16).reshape(-1, 2)
        mocker.patch(
            "vrcpilot.cli.mic.sys.stdin",
            new=_FakeStdin(samples.tobytes()),
        )

        exit_code = main(
            ["mic", "--rate", "48000", "--channels", "2", "--chunk-ms", "1"]
        )

        assert exit_code == 0
        chunks, rate = fake_mic.instances[0].played[0]
        assert rate == 48000
        joined = np.concatenate(chunks, axis=0)
        assert joined.shape == (48, 2)

    def test_stdin_wav_decoded(
        self,
        fake_mic: type[FakeMic],
        mocker: MockerFixture,
    ):
        samples = np.array([[100, -100], [200, -200]], dtype=np.int16)
        wav_bytes = _build_wav_bytes(samples, channels=2, rate=22050)
        mocker.patch(
            "vrcpilot.cli.mic.sys.stdin",
            new=_FakeStdin(wav_bytes),
        )

        # --format wav forces the WAV decoder on stdin (no extension to sniff).
        exit_code = main(["mic", "--format", "wav"])

        assert exit_code == 0
        chunks, rate = fake_mic.instances[0].played[0]
        # WAV ignores --rate; framerate comes from the header.
        assert rate == 22050
        assert chunks[0].shape == (2, 2)


class TestDeviceArgument:
    def test_device_flag_forwarded_to_mic(
        self,
        fake_mic: type[FakeMic],
        mocker: MockerFixture,
    ):
        mocker.patch("vrcpilot.cli.mic.sys.stdin", new=_FakeStdin(b""))

        exit_code = main(["mic", "--device", "CABLE Input"])

        assert exit_code == 0
        assert fake_mic.instances[0].device_argument == "CABLE Input"

    def test_default_device_is_none(
        self,
        fake_mic: type[FakeMic],
        mocker: MockerFixture,
    ):
        mocker.patch("vrcpilot.cli.mic.sys.stdin", new=_FakeStdin(b""))

        exit_code = main(["mic"])

        assert exit_code == 0
        # No --device → CLI defers to Mic's resolution chain by passing None.
        assert fake_mic.instances[0].device_argument is None


class TestErrorPaths:
    def test_mic_device_not_found_returns_1(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        # Patch Mic itself to raise the lookup error on construction.
        def _boom(_device: str | None = None) -> object:
            raise MicDeviceNotFoundError("no output device matches 'fake'")

        mocker.patch("vrcpilot.cli.mic.Mic", _boom)
        wav_path = tmp_path / "x.wav"
        _write_wav(wav_path, np.zeros((1, 2), dtype=np.int16), channels=2, rate=48000)

        exit_code = main(["mic", "-i", str(wav_path), "--device", "fake"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "no output device matches" in captured.err

    def test_import_error_returns_1(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        def _boom(_device: str | None = None) -> object:
            raise ImportError("sounddevice is not installed")

        mocker.patch("vrcpilot.cli.mic.Mic", _boom)
        wav_path = tmp_path / "x.wav"
        _write_wav(wav_path, np.zeros((1, 2), dtype=np.int16), channels=2, rate=48000)

        exit_code = main(["mic", "-i", str(wav_path)])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "sounddevice is not installed" in captured.err

    def test_port_audio_error_returns_1(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        # Synthesise a PortAudioError-shaped exception so the except
        # branch routing on ``type(exc).__name__`` is exercised.
        class PortAudioError(Exception):
            pass

        class _BoomMic:
            def __init__(self, _device: str | None = None) -> None:
                pass

            def play(
                self,
                stream: object,
                *,
                sample_rate: int = 48000,
            ) -> None:
                del stream, sample_rate
                raise PortAudioError("device unavailable")

        mocker.patch("vrcpilot.cli.mic.Mic", _BoomMic)
        wav_path = tmp_path / "x.wav"
        _write_wav(wav_path, np.zeros((1, 2), dtype=np.int16), channels=2, rate=48000)

        exit_code = main(["mic", "-i", str(wav_path)])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "device unavailable" in captured.err


class TestProgressOutput:
    def test_progress_on_stderr_only(
        self,
        fake_mic: type[FakeMic],
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_mic
        mocker.patch("vrcpilot.cli.mic.sys.stdin", new=_FakeStdin(b""))

        exit_code = main(["mic"])

        assert exit_code == 0
        captured = capsys.readouterr()
        # Stdout must stay silent so mic can sit at the tail of a pipe.
        assert captured.out == ""
        assert "Playing audio" in captured.err
