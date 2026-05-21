"""Tests for :mod:`vrcpilot.cli.record`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from pytest_mock import MockerFixture, MockType

from tests.fakes import FakeRawPcmStdoutSink, FakeSpeakerLoop, FakeWavSink
from vrcpilot.cli import main


@dataclass
class _RecordFakes:
    loop: type[FakeSpeakerLoop]
    sink: type[FakeWavSink]
    pcm: type[FakeRawPcmStdoutSink]
    sleep: MockType


@pytest.fixture
def record_fakes(mocker: MockerFixture) -> _RecordFakes:
    """Wire the canonical record fakes into :mod:`vrcpilot.cli`.

    ``time.sleep`` is patched to raise ``KeyboardInterrupt`` so the
    production ``while True: time.sleep(3600)`` idiom exits on the
    first call. Without this, ``Mock.call_args_list`` accumulates
    forever and starves the runner of memory.

    ``sys.stdout.isatty`` is pinned to ``False`` so the default
    (no ``-o``) path enters pipe mode regardless of how the test
    suite is invoked. Tests that exercise the TTY-refusal branch
    re-patch it via their own ``mocker.patch`` call.
    """
    sleep_mock = mocker.patch(
        "vrcpilot.cli.record.time.sleep", side_effect=KeyboardInterrupt
    )
    mocker.patch("vrcpilot.cli.record.SpeakerLoop", FakeSpeakerLoop)
    mocker.patch("vrcpilot.cli.record.WavFileSink", FakeWavSink)
    mocker.patch("vrcpilot.cli.record.RawPcmStdoutSink", FakeRawPcmStdoutSink)
    mocker.patch("sys.stdout.isatty", lambda: False)
    FakeSpeakerLoop.instances = []
    FakeSpeakerLoop.frames_per_start = 3
    FakeSpeakerLoop.samples_per_frame = 1024
    FakeSpeakerLoop.init_side_effect = None
    FakeWavSink.instances = []
    FakeRawPcmStdoutSink.instances = []
    return _RecordFakes(
        loop=FakeSpeakerLoop,
        sink=FakeWavSink,
        pcm=FakeRawPcmStdoutSink,
        sleep=sleep_mock,
    )


class TestRecordCommand:
    def test_no_output_streams_raw_pcm_to_stdout_sink(
        self,
        record_fakes: _RecordFakes,
        capsys: pytest.CaptureFixture[str],
    ):
        exit_code = main(["record"])

        assert exit_code == 0
        # Pipe mode constructs the raw-PCM sink, not the WAV sink.
        assert len(record_fakes.pcm.instances) == 1
        assert len(record_fakes.sink.instances) == 0
        captured = capsys.readouterr()
        # Pipe mode owns stdout for the binary s16le payload; Python
        # must not write anything else to it.
        assert captured.out == ""
        # Progress chatter on stderr advertises the pipe target.
        assert "stdout" in captured.err
        assert "s16le" in captured.err

    def test_no_output_refuses_when_stdout_is_tty(
        self,
        record_fakes: _RecordFakes,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        # Override the fixture default: pretend stdout is a TTY.
        mocker.patch("sys.stdout.isatty", lambda: True)

        exit_code = main(["record"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "refusing to write a raw PCM stream to a TTY" in captured.err
        assert captured.out == ""
        # Neither sink is even constructed when refusing.
        assert record_fakes.pcm.instances == []
        assert record_fakes.sink.instances == []
        # And the speaker loop is not started.
        assert record_fakes.loop.instances == []

    def test_output_directory_uses_default_filename_inside(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        exit_code = main(["record", "-o", str(tmp_path)])

        assert exit_code == 0
        assert len(record_fakes.sink.instances) == 1
        sink = record_fakes.sink.instances[0]
        assert sink.output_path.parent == tmp_path
        assert sink.output_path.name.startswith("vrcpilot_record_")
        assert sink.output_path.suffix == ".wav"
        # No raw-PCM sink in file mode.
        assert record_fakes.pcm.instances == []
        captured = capsys.readouterr()
        assert captured.out.strip() == str(sink.output_path.resolve())

    def test_explicit_output_path(self, record_fakes: _RecordFakes, tmp_path: Path):
        out = tmp_path / "foo.wav"

        exit_code = main(["record", "--output", str(out)])

        assert exit_code == 0
        assert record_fakes.sink.instances[0].output_path == out

    def test_short_output_flag(self, record_fakes: _RecordFakes, tmp_path: Path):
        out = tmp_path / "bar.wav"

        exit_code = main(["record", "-o", str(out)])

        assert exit_code == 0
        assert record_fakes.sink.instances[0].output_path == out

    def test_duration_argument_propagates(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        mocker: MockerFixture,
    ):
        # Override the fixture's KeyboardInterrupt sleep with a
        # well-behaved one so the ``--duration`` branch can complete
        # naturally.
        sleep_mock = mocker.patch("vrcpilot.cli.record.time.sleep", return_value=None)

        exit_code = main(["record", "-o", str(tmp_path / "d.wav"), "--duration", "5"])

        assert exit_code == 0
        sleep_mock.assert_called_once_with(5.0)
        assert record_fakes.sink.instances[0].closed

    def test_no_duration_waits_until_keyboard_interrupt(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ):
        # Default fixture sleep raises KeyboardInterrupt -> the
        # ``while True: time.sleep(3600)`` idiom exits on the first
        # call. The assertion locks in the call_count to guard the
        # memory-pressure trap (feedback_just_run_memory_pressure).
        exit_code = main(["record", "-o", str(tmp_path / "ki.wav")])

        assert exit_code == 0
        assert record_fakes.sleep.call_count == 1

    def test_zero_samples_returns_error(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        record_fakes.loop.frames_per_start = 0

        exit_code = main(["record", "-o", str(tmp_path / "zero.wav")])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "no audio samples recorded" in captured.err
        assert record_fakes.sink.instances[0].sample_count == 0
        # No path emitted to stdout on failure.
        assert captured.out == ""

    def test_runtime_error_returns_error(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        record_fakes.loop.init_side_effect = RuntimeError("VRChat is not running")

        exit_code = main(["record", "-o", str(tmp_path / "err.wav")])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "VRChat is not running" in captured.err
        assert captured.out == ""

    def test_callback_writes_frames_to_sink(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ):
        record_fakes.loop.frames_per_start = 5
        record_fakes.loop.samples_per_frame = 1024

        exit_code = main(["record", "-o", str(tmp_path / "cb.wav")])

        assert exit_code == 0
        sink = record_fakes.sink.instances[0]
        # 5 frames * 1024 samples per frame == 5120 total samples.
        assert sink.sample_count == 5 * 1024
        assert sink.closed

    def test_progress_message_is_on_stderr_not_stdout(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del record_fakes
        out = tmp_path / "progress.wav"

        exit_code = main(["record", "-o", str(out)])

        assert exit_code == 0
        captured = capsys.readouterr()
        # Progress chatter must not pollute stdout; only the absolute
        # path is emitted there.
        assert "Recording audio to" not in captured.out
        assert "Press Ctrl+C" not in captured.out
        # ...and it must be present on stderr instead.
        assert "Recording audio to" in captured.err
        assert "Press Ctrl+C" in captured.err

    def test_stdout_is_absolute_path(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        del record_fakes
        out = tmp_path / "abs.wav"

        exit_code = main(["record", "-o", str(out)])

        assert exit_code == 0
        stdout = capsys.readouterr().out.strip()
        assert Path(stdout).is_absolute()
        assert Path(stdout) == out.resolve()
