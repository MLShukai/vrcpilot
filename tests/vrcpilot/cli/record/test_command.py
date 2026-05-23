"""Integration tests for :mod:`vrcpilot.cli.record` (CLI entry-point)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from pytest_mock import MockerFixture, MockType

from tests.fakes import (
    FakeCaptureLoop,
    FakeMkvStdoutMuxer,
    FakeMp4FileMuxer,
    FakeSpeakerLoop,
    FakeWavFileMuxer,
)
from vrcpilot.cli import main
from vrcpilot.process import VRChatMultipleInstancesError


@dataclass
class _RecordFakes:
    """Convenience bag holding the patched fakes for one test."""

    capture_loop: type[FakeCaptureLoop]
    speaker_loop: type[FakeSpeakerLoop]
    mp4: type[FakeMp4FileMuxer]
    wav: type[FakeWavFileMuxer]
    mkv: type[FakeMkvStdoutMuxer]
    sleep: MockType


@pytest.fixture
def record_fakes(mocker: MockerFixture) -> _RecordFakes:
    """Wire the canonical record fakes into :mod:`vrcpilot.cli.record`.

    ``time.sleep`` is patched to raise ``KeyboardInterrupt`` so the
    production ``while True: time.sleep(3600)`` idiom exits on the
    first call. Tests that need a well-behaved sleep re-patch it.

    ``sys.stdout.isatty`` is pinned to ``False`` so the default
    (no ``-o``) path enters pipe mode regardless of how the test
    suite is invoked. Tests that exercise the TTY-refusal branch
    re-patch it via their own ``mocker.patch`` call.

    All class-level state on the four fakes is reset so the
    ``instances`` lists do not leak between tests.
    """
    sleep_mock = mocker.patch(
        "vrcpilot.cli.record.time.sleep", side_effect=KeyboardInterrupt
    )
    mocker.patch("vrcpilot.cli.record.CaptureLoop", FakeCaptureLoop)
    mocker.patch("vrcpilot.cli.record.SpeakerLoop", FakeSpeakerLoop)
    mocker.patch("vrcpilot.cli.record.Mp4FileMuxer", FakeMp4FileMuxer)
    mocker.patch("vrcpilot.cli.record.WavFileMuxer", FakeWavFileMuxer)
    mocker.patch("vrcpilot.cli.record.MkvStdoutMuxer", FakeMkvStdoutMuxer)
    mocker.patch("sys.stdout.isatty", lambda: False)
    FakeCaptureLoop.instances = []
    FakeCaptureLoop.frames_per_start = 3
    FakeCaptureLoop.init_side_effect = None
    FakeSpeakerLoop.instances = []
    FakeSpeakerLoop.frames_per_start = 3
    FakeSpeakerLoop.samples_per_frame = 1024
    FakeSpeakerLoop.init_side_effect = None
    FakeMp4FileMuxer.reset()
    FakeWavFileMuxer.reset()
    FakeMkvStdoutMuxer.reset()
    return _RecordFakes(
        capture_loop=FakeCaptureLoop,
        speaker_loop=FakeSpeakerLoop,
        mp4=FakeMp4FileMuxer,
        wav=FakeWavFileMuxer,
        mkv=FakeMkvStdoutMuxer,
        sleep=sleep_mock,
    )


# ---------------------------------------------------------------------------
# Mode dispatch (truth table)
# ---------------------------------------------------------------------------


class TestModeDispatch:
    """Cover the 12-row truth table from the spec.

    Each parametrised case asserts (a) which fake muxer was
    constructed, (b) the ``video`` / ``audio`` constructor flags on
    that muxer, and (c) which of the two loops are started so the
    ``ExitStack`` driving logic stays honest.
    """

    @pytest.mark.parametrize(
        "argv_extra,output_kind,expected_muxer,want_video,want_audio",
        [
            # (--video, --audio) both implicit
            pytest.param([], None, "mkv", True, True, id="both-stdout"),
            pytest.param([], "dir", "mp4", True, True, id="both-dir"),
            pytest.param([], "mp4", "mp4", True, True, id="both-mp4"),
            # --video only
            pytest.param(["--video"], None, "mkv", True, False, id="video-stdout"),
            pytest.param(["--video"], "dir", "mp4", True, False, id="video-dir"),
            pytest.param(["--video"], "mp4", "mp4", True, False, id="video-mp4"),
            # --audio only
            pytest.param(["--audio"], None, "mkv", False, True, id="audio-stdout"),
            pytest.param(["--audio"], "dir", "wav", False, True, id="audio-dir"),
            pytest.param(["--audio"], "wav", "wav", False, True, id="audio-wav"),
            # both flags explicit (collapses to "both")
            pytest.param(
                ["--video", "--audio"],
                None,
                "mkv",
                True,
                True,
                id="both-explicit-stdout",
            ),
            pytest.param(
                ["--video", "--audio"], "dir", "mp4", True, True, id="both-explicit-dir"
            ),
            pytest.param(
                ["--video", "--audio"], "mp4", "mp4", True, True, id="both-explicit-mp4"
            ),
        ],
    )
    def test_mode_dispatch(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        argv_extra: list[str],
        output_kind: str | None,
        expected_muxer: str,
        want_video: bool,
        want_audio: bool,
    ) -> None:
        argv: list[str] = ["record", *argv_extra]
        if output_kind == "dir":
            argv += ["-o", str(tmp_path)]
        elif output_kind == "mp4":
            argv += ["-o", str(tmp_path / "out.mp4")]
        elif output_kind == "wav":
            argv += ["-o", str(tmp_path / "out.wav")]

        exit_code = main(argv)
        assert exit_code == 0

        # Exactly one muxer of the expected concrete kind is built.
        if expected_muxer == "mp4":
            assert len(record_fakes.mp4.instances) == 1
            assert record_fakes.wav.instances == []
            assert record_fakes.mkv.instances == []
            muxer = record_fakes.mp4.instances[0]
            assert muxer.video is want_video
            assert muxer.audio is want_audio
        elif expected_muxer == "wav":
            assert len(record_fakes.wav.instances) == 1
            assert record_fakes.mp4.instances == []
            assert record_fakes.mkv.instances == []
        else:  # mkv
            assert len(record_fakes.mkv.instances) == 1
            assert record_fakes.mp4.instances == []
            assert record_fakes.wav.instances == []
            muxer_stdout = record_fakes.mkv.instances[0]
            assert muxer_stdout.video is want_video
            assert muxer_stdout.audio is want_audio

        # Loops are only spun up for the streams we are actually
        # recording. WAV file mode is audio-only, so CaptureLoop must
        # not even be constructed even though the muxer subclass would
        # technically accept ``write_video`` calls that raise.
        capture_started = bool(record_fakes.capture_loop.instances) and want_video
        speaker_started = bool(record_fakes.speaker_loop.instances) and want_audio
        assert capture_started == want_video
        assert speaker_started == want_audio


# ---------------------------------------------------------------------------
# Extension validation (exit 2)
# ---------------------------------------------------------------------------


class TestExtensionValidation:
    def test_both_mode_rejects_non_mp4(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        out = tmp_path / "foo.mkv"
        exit_code = main(["record", "-o", str(out)])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert (
            f"vrcpilot: video+audio output requires .mp4 (got: '{out}')" in captured.err
        )
        # No muxer is constructed when args are rejected.
        assert record_fakes.mp4.instances == []
        assert record_fakes.wav.instances == []
        assert record_fakes.mkv.instances == []

    def test_video_mode_rejects_wav(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        out = tmp_path / "foo.wav"
        exit_code = main(["record", "--video", "-o", str(out)])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert f"vrcpilot: --video requires .mp4 output (got: '{out}')" in captured.err
        assert record_fakes.mp4.instances == []
        assert record_fakes.wav.instances == []

    def test_audio_mode_rejects_mp4(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        out = tmp_path / "foo.mp4"
        exit_code = main(["record", "--audio", "-o", str(out)])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert f"vrcpilot: --audio requires .wav output (got: '{out}')" in captured.err
        assert record_fakes.mp4.instances == []
        assert record_fakes.wav.instances == []

    def test_directory_picks_default_filename_for_mode_both(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = main(["record", "-o", str(tmp_path)])

        assert exit_code == 0
        assert len(record_fakes.mp4.instances) == 1
        sink = record_fakes.mp4.instances[0]
        assert sink.output_path.parent == tmp_path
        assert sink.output_path.name.startswith("vrcpilot_record_")
        assert sink.output_path.suffix == ".mp4"
        captured = capsys.readouterr()
        assert captured.out.strip() == str(sink.output_path.resolve())

    def test_directory_picks_default_filename_for_mode_video(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
    ) -> None:
        exit_code = main(["record", "--video", "-o", str(tmp_path)])

        assert exit_code == 0
        assert len(record_fakes.mp4.instances) == 1
        assert record_fakes.mp4.instances[0].output_path.suffix == ".mp4"

    def test_directory_picks_default_filename_for_mode_audio(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
    ) -> None:
        exit_code = main(["record", "--audio", "-o", str(tmp_path)])

        assert exit_code == 0
        assert len(record_fakes.wav.instances) == 1
        sink = record_fakes.wav.instances[0]
        assert sink.output_path.parent == tmp_path
        assert sink.output_path.name.startswith("vrcpilot_record_")
        assert sink.output_path.suffix == ".wav"


# ---------------------------------------------------------------------------
# Stdout / TTY guard
# ---------------------------------------------------------------------------


class TestStdoutMode:
    def test_no_output_streams_mkv_to_stdout_for_both(
        self,
        record_fakes: _RecordFakes,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = main(["record"])

        assert exit_code == 0
        assert len(record_fakes.mkv.instances) == 1
        assert record_fakes.mp4.instances == []
        assert record_fakes.wav.instances == []
        captured = capsys.readouterr()
        # Pipe mode owns stdout for the binary MKV payload; Python
        # must not write anything else to it.
        assert captured.out == ""
        # Progress chatter on stderr advertises the pipe target.
        assert "stdout" in captured.err
        assert "MKV" in captured.err

    def test_no_output_video_only_picks_mkv(self, record_fakes: _RecordFakes) -> None:
        exit_code = main(["record", "--video"])

        assert exit_code == 0
        assert len(record_fakes.mkv.instances) == 1
        muxer = record_fakes.mkv.instances[0]
        assert muxer.video is True
        assert muxer.audio is False

    def test_no_output_audio_only_picks_mkv(self, record_fakes: _RecordFakes) -> None:
        exit_code = main(["record", "--audio"])

        assert exit_code == 0
        assert len(record_fakes.mkv.instances) == 1
        muxer = record_fakes.mkv.instances[0]
        assert muxer.video is False
        assert muxer.audio is True

    def test_no_output_refuses_when_stdout_is_tty(
        self,
        record_fakes: _RecordFakes,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mocker.patch("sys.stdout.isatty", lambda: True)

        exit_code = main(["record"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert (
            "vrcpilot: refusing to write a MKV stream to a TTY; "
            "pipe stdout or pass -o <path>" in captured.err
        )
        assert captured.out == ""
        # No muxer, no loop -- bail before constructing anything.
        assert record_fakes.mkv.instances == []
        assert record_fakes.mp4.instances == []
        assert record_fakes.wav.instances == []
        assert record_fakes.capture_loop.instances == []
        assert record_fakes.speaker_loop.instances == []


# ---------------------------------------------------------------------------
# --fps validation and propagation
# ---------------------------------------------------------------------------


class TestFpsHandling:
    def test_default_fps_is_30_in_stdout_mode(self, record_fakes: _RecordFakes) -> None:
        exit_code = main(["record"])

        assert exit_code == 0
        assert record_fakes.mkv.instances[0].fps == 30.0
        assert record_fakes.capture_loop.instances[0].fps == 30.0

    def test_default_fps_is_30_in_file_mode(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        exit_code = main(["record", "-o", str(tmp_path / "x.mp4")])

        assert exit_code == 0
        assert record_fakes.mp4.instances[0].fps == 30.0
        assert record_fakes.capture_loop.instances[0].fps == 30.0

    def test_explicit_fps_propagates_to_mp4_muxer_and_loop(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        exit_code = main(["record", "--fps", "60", "-o", str(tmp_path / "x.mp4")])

        assert exit_code == 0
        assert record_fakes.mp4.instances[0].fps == 60.0
        assert record_fakes.capture_loop.instances[0].fps == 60.0

    def test_explicit_fps_with_video_only(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        exit_code = main(
            ["record", "--video", "--fps", "60", "-o", str(tmp_path / "x.mp4")]
        )

        assert exit_code == 0
        assert record_fakes.mp4.instances[0].fps == 60.0
        assert record_fakes.capture_loop.instances[0].fps == 60.0

    def test_explicit_fps_with_stdout_mkv(self, record_fakes: _RecordFakes) -> None:
        exit_code = main(["record", "--fps", "60"])

        assert exit_code == 0
        assert record_fakes.mkv.instances[0].fps == 60.0
        assert record_fakes.capture_loop.instances[0].fps == 60.0

    def test_fps_with_audio_only_rejected(
        self,
        record_fakes: _RecordFakes,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        exit_code = main(
            ["record", "--audio", "--fps", "60", "-o", str(tmp_path / "x.wav")]
        )

        assert exit_code == 2
        captured = capsys.readouterr()
        assert (
            "vrcpilot: --fps is not meaningful with --audio "
            "(drop --fps or remove --audio)" in captured.err
        )
        # Nothing should be constructed before the validation gate.
        assert record_fakes.wav.instances == []
        assert record_fakes.mp4.instances == []
        assert record_fakes.mkv.instances == []
        assert record_fakes.capture_loop.instances == []
        assert record_fakes.speaker_loop.instances == []


# ---------------------------------------------------------------------------
# --duration / KeyboardInterrupt
# ---------------------------------------------------------------------------


class TestDuration:
    def test_duration_argument_propagates(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        mocker: MockerFixture,
    ) -> None:
        # Override the fixture's KeyboardInterrupt sleep with a
        # well-behaved one so the ``--duration`` branch can complete
        # naturally.
        sleep_mock = mocker.patch("vrcpilot.cli.record.time.sleep", return_value=None)

        exit_code = main(["record", "-o", str(tmp_path / "d.mp4"), "--duration", "5"])

        assert exit_code == 0
        sleep_mock.assert_called_once_with(5.0)
        assert record_fakes.mp4.instances[0].closed

    def test_no_duration_waits_until_keyboard_interrupt(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        # Default fixture sleep raises KeyboardInterrupt -> the
        # ``while True: time.sleep(3600)`` idiom exits on the first
        # call. The assertion locks in the call_count to guard the
        # memory-pressure trap.
        exit_code = main(["record", "-o", str(tmp_path / "ki.mp4")])

        assert exit_code == 0
        assert record_fakes.sleep.call_count == 1


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrors:
    def test_capture_loop_runtime_error_returns_one(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_fakes.capture_loop.init_side_effect = RuntimeError(
            "VRChat is not running"
        )

        exit_code = main(["record", "-o", str(tmp_path / "err.mp4")])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "vrcpilot: VRChat is not running" in captured.err
        assert captured.out == ""

    def test_speaker_loop_runtime_error_returns_one(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_fakes.speaker_loop.init_side_effect = RuntimeError(
            "VRChat is not running"
        )

        exit_code = main(["record", "--audio", "-o", str(tmp_path / "err.wav")])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "vrcpilot: VRChat is not running" in captured.err
        assert captured.out == ""

    def test_zero_frames_and_samples_returns_one(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_fakes.capture_loop.frames_per_start = 0
        record_fakes.speaker_loop.frames_per_start = 0

        exit_code = main(["record", "-o", str(tmp_path / "zero.mp4")])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "vrcpilot: no frames or audio samples were recorded" in captured.err
        assert captured.out == ""

    def test_video_only_with_zero_frames_returns_one(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_fakes.capture_loop.frames_per_start = 0

        exit_code = main(["record", "--video", "-o", str(tmp_path / "z.mp4")])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "no frames or audio samples were recorded" in captured.err

    def test_audio_only_with_zero_samples_returns_one(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_fakes.speaker_loop.frames_per_start = 0

        exit_code = main(["record", "--audio", "-o", str(tmp_path / "z.wav")])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "no frames or audio samples were recorded" in captured.err


# ---------------------------------------------------------------------------
# Callback wiring + side effects
# ---------------------------------------------------------------------------


class TestCallbackWiring:
    def test_video_callback_writes_to_muxer(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        record_fakes.capture_loop.frames_per_start = 5
        record_fakes.speaker_loop.frames_per_start = 0

        exit_code = main(["record", "-o", str(tmp_path / "cb.mp4")])

        assert exit_code == 0
        muxer = record_fakes.mp4.instances[0]
        assert muxer.frame_count == 5

    def test_audio_callback_writes_to_muxer(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        record_fakes.capture_loop.frames_per_start = 0
        record_fakes.speaker_loop.frames_per_start = 4
        record_fakes.speaker_loop.samples_per_frame = 256

        exit_code = main(["record", "--audio", "-o", str(tmp_path / "cb.wav")])

        assert exit_code == 0
        muxer = record_fakes.wav.instances[0]
        assert muxer.sample_count == 4 * 256

    def test_both_loops_feed_one_muxer(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        record_fakes.capture_loop.frames_per_start = 2
        record_fakes.speaker_loop.frames_per_start = 3
        record_fakes.speaker_loop.samples_per_frame = 128

        exit_code = main(["record", "-o", str(tmp_path / "both.mp4")])

        assert exit_code == 0
        muxer = record_fakes.mp4.instances[0]
        assert muxer.frame_count == 2
        assert muxer.sample_count == 3 * 128
        assert muxer.closed

    def test_muxer_is_closed_after_run(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        exit_code = main(["record", "-o", str(tmp_path / "c.mp4")])

        assert exit_code == 0
        assert record_fakes.mp4.instances[0].closed


# ---------------------------------------------------------------------------
# Progress chatter and stdout discipline
# ---------------------------------------------------------------------------


class TestProgressMessaging:
    def test_progress_on_stderr_not_stdout(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del record_fakes
        out = tmp_path / "progress.mp4"

        exit_code = main(["record", "-o", str(out)])

        assert exit_code == 0
        captured = capsys.readouterr()
        # Progress chatter must not pollute stdout; only the absolute
        # path is emitted there.
        assert "Recording to" not in captured.out
        assert "Press Ctrl+C" not in captured.out
        # ...and it must be present on stderr instead.
        assert "Recording to" in captured.err
        assert "Press Ctrl+C" in captured.err

    def test_stdout_is_absolute_path(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del record_fakes
        out = tmp_path / "abs.mp4"

        exit_code = main(["record", "-o", str(out)])

        assert exit_code == 0
        stdout = capsys.readouterr().out.strip()
        assert Path(stdout).is_absolute()
        assert Path(stdout) == out.resolve()

    def test_stdout_pipe_emits_no_path_line(
        self,
        record_fakes: _RecordFakes,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del record_fakes

        exit_code = main(["record"])

        assert exit_code == 0
        captured = capsys.readouterr()
        # Pipe mode: stdout must stay byte-clean for the MKV payload.
        assert captured.out == ""


# ---------------------------------------------------------------------------
# --pid plumbing (multi-instance VRChat targeting)
# ---------------------------------------------------------------------------


class TestPidArg:
    """``--pid`` should reach both ``CaptureLoop`` and ``SpeakerLoop``."""

    def test_passes_pid_to_both_loops(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        exit_code = main(["record", "-o", str(tmp_path / "pid.mp4"), "--pid", "8765"])

        assert exit_code == 0
        assert len(record_fakes.capture_loop.instances) == 1
        assert record_fakes.capture_loop.instances[0].pid == 8765
        assert len(record_fakes.speaker_loop.instances) == 1
        assert record_fakes.speaker_loop.instances[0].pid == 8765

    def test_no_pid_passes_none(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        exit_code = main(["record", "-o", str(tmp_path / "nopid.mp4")])

        assert exit_code == 0
        assert record_fakes.capture_loop.instances[0].pid is None
        assert record_fakes.speaker_loop.instances[0].pid is None

    def test_video_only_passes_pid_to_capture(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        # In ``--video`` mode SpeakerLoop is never constructed; only
        # CaptureLoop should receive the pid kwarg.
        exit_code = main(
            ["record", "--video", "-o", str(tmp_path / "v.mp4"), "--pid", "111"]
        )

        assert exit_code == 0
        assert record_fakes.capture_loop.instances[0].pid == 111
        assert record_fakes.speaker_loop.instances == []

    def test_audio_only_passes_pid_to_speaker(
        self, record_fakes: _RecordFakes, tmp_path: Path
    ) -> None:
        exit_code = main(
            ["record", "--audio", "-o", str(tmp_path / "a.wav"), "--pid", "222"]
        )

        assert exit_code == 0
        assert record_fakes.speaker_loop.instances[0].pid == 222
        assert record_fakes.capture_loop.instances == []

    def test_multiple_instances_exits_with_diagnostic(
        self,
        record_fakes: _RecordFakes,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # CaptureLoop's constructor surfaces VRChatMultipleInstancesError
        # when --pid is omitted on a multi-instance host. The CLI must
        # map that to the shared multi-instance diagnostic (exit 1).
        record_fakes.capture_loop.init_side_effect = VRChatMultipleInstancesError(
            [900, 901]
        )

        exit_code = main(["record", "-o", str(tmp_path / "multi.mp4")])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert (
            captured.err.splitlines()[-1]
            == "vrcpilot: multiple VRChat instances detected "
            "(PIDs: 900 901); pass --pid"
        )
