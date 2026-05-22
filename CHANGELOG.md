# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Breaking

- Removed the `vrcpilot capture` subcommand. Its functionality is folded into `vrcpilot record --video` (MP4 file output) and `vrcpilot record --video` without `-o` (self-describing MKV byte stream over stdout). The legacy `y4m` stdout format is gone.
- Removed `vrcpilot.speaker.WavFileSink` and `vrcpilot.speaker.RawPcmStdoutSink` from the public API (they were re-exported by mistake; `vrcpilot.capture.Mp4FrameSink` / `Y4mStdoutFrameSink` were never public). The CLI now uses internal PyAV-backed muxers (`vrcpilot.cli.record.muxer`, intentionally not part of the public surface). Users who composed the old sinks directly should write their own writer on top of `CaptureLoop` / `SpeakerLoop` — see [`docs/python-api.md`](docs/python-api.md).

### Added

- `vrcpilot record` now records video, audio, or both in a single subcommand. The `--video` / `--audio` flags select the mode (passing both, or neither, records both video and audio). File output is MP4 for video / both modes (`-o file.mp4` or a directory argument) and WAV for audio-only mode (`--audio -o file.wav`); a mismatched extension exits `2`. With `-o` omitted, the recording is streamed to stdout as a self-describing Matroska (MKV) container (libx264 + AAC) regardless of mode, so downstream tools like `ffmpeg -i -` can consume it directly.
- New `--fps FLOAT` flag on `vrcpilot record` (default `30.0`); combining it with `--audio` alone is rejected with exit `2` and `vrcpilot: --fps is not meaningful with --audio (drop --fps or remove --audio)`.

### Changed

- PyAV (`av>=12,<16`) is now a runtime dependency, replacing `cv2.VideoWriter` and the standard `wave` module for the record subcommand's muxing path.

## [0.1.0] - 2026-05-15

First stable release. The release pipeline rehearsed in `0.1.0rc1` is now promoted to stable; the Python and CLI surfaces are unchanged from the release candidate.

### Changed

- `Development Status` classifier promoted from `3 - Alpha` to `4 - Beta` (0.x stable, pre-1.0 maturity).
- README installation instructions now lead with the stable command (`pip install vrcpilot` / `uv tool install vrcpilot`); the pre-release variant (`--pre`) is documented as an opt-in.

## [0.1.0rc1] - 2026-05-15

First public release candidate. Validates the end-to-end publish pipeline before the stable `0.1.0` tag.

### Added

- **Process control**: `vrcpilot.launch`, `vrcpilot.terminate`, `vrcpilot.find_pid`, and `OscConfig`.
- **Window control**: `focus`, `unfocus`, `is_foreground` on Windows (Win32) and Linux (X11 / XWayland).
- **Screen capture**: `Capture` and `CaptureLoop` with `Mp4FrameSink` / `Y4mStdoutFrameSink`; one-shot `take_screenshot` returning a `Screenshot` value object that round-trips through YAML (file-path or inline base64 PNG).
- **OCR**: swappable `OCREngine` ABC with `RapidOCREngine` implementation; `ocr()` consumes a `Screenshot` and returns word-level results with both window-local and desktop-absolute coordinates.
- **Image-template detection**: `DetectEngine` ABC with `TemplateDetectEngine` (OpenCV `TM_CCOEFF_NORMED`); `detect()` returns coordinate-bearing detections with the same coordinate schema as OCR.
- **Synthetic input**: keyboard / mouse via `pydirectinput` (Windows `SendInput`) and `inputtino` (Linux `/dev/uinput`), with VRChat focus-guarding (`ensure_target`, `VRChatNotFocusedError`).
- **Non-ASCII text injection**: `vrcpilot.clipboard` uses pyperclip + Ctrl+V to bypass scancode-keyboard limitations.
- **OSC subsystem** (`vrcpilot.osc`): `OscSender`, `InputController`, and `AvatarParameters` for sending VRChat OSC traffic: button inputs, axis values, chatbox text, typing indicator, and avatar parameters.
- **CLI front-end** (`vrcpilot ...`): `launch`, `pid`, `terminate`, `focus`, `unfocus`, `screenshot`, `capture`, `mouse`, `keyboard`, `paste`, `ocr`, `detect`, and `osc` (with `send` / `axis` / `tap` / `hold` / `chatbox` / `typing` / `avatar` actions). The `screenshot` output YAML is the standard hand-off format between subcommands.
- **Shell completion**: argcomplete-driven Tab completion for bash / Git Bash / PowerShell, with `clicomp.sh` / `CliComp.ps1` bootstrap scripts.
- **Tag-driven PyPI publish workflow** (`.github/workflows/publish.yml`) with a Test PyPI -> PyPI -> GitHub Release chain, Trusted Publishing (OIDC), and sigstore signing of built artifacts.
- **Release engineering documentation**: `CONTRIBUTING.md` codifies the branching, release, hotfix, and pre-release tag conventions, and a new `docs/RELEASE.md` runbook documents the procedure for release engineers.

### Platforms

- Windows 10 / 11
- Linux with X11 or XWayland sessions (Wayland-native is unsupported; `focus`/`unfocus` warn and return `False`)
- macOS is out of scope.

[0.1.0]: https://github.com/MLShukai/vrcpilot/compare/v0.1.0rc1...v0.1.0
[0.1.0rc1]: https://github.com/MLShukai/vrcpilot/releases/tag/v0.1.0rc1
[unreleased]: https://github.com/MLShukai/vrcpilot/compare/v0.1.0...HEAD
