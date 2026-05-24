"""Tests for :mod:`vrcpilot.cli.mic`.

``vrcpilot mic`` streams PCM (WAV or raw s16le) into a virtual mic
device. The real device side (``soundcard`` + ``libpulse`` / WASAPI)
needs a working audio stack; success-path verification is deferred to
the e2e suite. The CLI also enforces input-shape contracts before
opening the device, and those *are* exercisable without audio
hardware:

* ``-i -`` with a TTY stdin (no piped data) -> exit 2.
* ``--format auto`` with a non-WAV file path -> exit 2.
* WAV file with non-16-bit PCM -> exit 1 via ``wave.Error``.

Argparse plumbing is verified through :func:`vrcpilot.cli.build_parser`.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from vrcpilot.cli import build_parser, main


class TestMicArgparse:
    def test_defaults(self):
        ns = build_parser().parse_args(["mic"])
        # Default input is stdin ("-"), rate=48000, channels=2,
        # format=auto, chunk_ms=100.
        assert ns.input == "-"
        assert ns.rate == 48000
        assert ns.channels == 2
        assert ns.format == "auto"
        assert ns.chunk_ms == 100
        assert ns.device is None

    def test_device_flag(self):
        ns = build_parser().parse_args(["mic", "--device", "CABLE Input"])
        assert ns.device == "CABLE Input"

    def test_input_flag(self):
        ns = build_parser().parse_args(["mic", "-i", "/tmp/sample.wav"])
        assert ns.input == "/tmp/sample.wav"

    def test_format_choice(self):
        ns = build_parser().parse_args(["mic", "--format", "s16le"])
        assert ns.format == "s16le"

    def test_format_rejects_unknown_choice(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["mic", "--format", "mp3"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_channels_choice(self):
        ns = build_parser().parse_args(["mic", "--channels", "1"])
        assert ns.channels == 1

    def test_channels_rejects_out_of_choice(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["mic", "--channels", "4"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""


class TestMicInputResolution:
    """Pre-device-open input validation surfaces as exit 2 or 1."""

    def test_stdin_dash_on_tty_exits_2(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # The autouse ``_stdin_is_tty_by_default`` patches
        # ``vrcpilot.cli._common.sys.stdin.isatty`` -- the mic CLI
        # reads ``sys.stdin.isatty`` from its own namespace, but
        # ``sys.stdin`` is a singleton so the same ``isatty`` patch
        # affects both modules.
        assert main(["mic", "-i", "-"]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: no audio piped to stdin" in captured.err

    def test_auto_format_non_wav_path_exits_2(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``--format auto`` against a file path that doesn't end in
        # .wav cannot be auto-detected; the CLI prints a guidance line
        # and exits 2.
        target = tmp_path / "audio.raw"
        target.write_bytes(b"")
        assert main(["mic", "-i", str(target)]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "cannot auto-detect format" in captured.err

    def test_wav_with_bad_sampwidth_exits_1(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        # Hand-build a WAV with 8-bit samples; the CLI's
        # ``_wav_to_float32`` rejects anything other than 16-bit.
        target = tmp_path / "8bit.wav"
        with wave.open(str(target), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)  # 8-bit -- not supported
            w.setframerate(48000)
            w.writeframes(b"\x00" * 100)
        assert main(["mic", "-i", str(target)]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err
        assert "sampwidth" in captured.err
