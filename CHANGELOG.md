# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Virtual mic output** (`vrcpilot.mic`): `Mic` opens a sounddevice
  OutputStream in its constructor for a fixed `(sample_rate, channels)`
  and writes one float32 chunk per `play(chunk)` call, so callers drive
  the cadence (`for chunk in tts.stream(): mic.play(chunk)`). The
  session is released via context manager, explicit `close()`, or the
  finaliser. Windows uses VB-Audio Virtual Cable as the default
  (`"CABLE Input"`); Linux/macOS require an explicit `device=` /
  `$VRCPILOT_MIC_DEVICE` (default device names are reserved for a
  follow-up).
- **CLI**: `vrcpilot mic` subcommand. Reads stdin by default so
  `vrcpilot record -o - | vrcpilot mic` works; also accepts `-i path.wav` for
  16-bit signed PCM WAV files, with `--format {auto,wav,s16le}`,
  `--rate`, `--channels`, `--chunk-ms`, and `--device` overrides.
- `vrcpilot.MicDeviceNotFoundError` raised when sounddevice cannot find a
  matching output device.
- `VRCPILOT_MIC_DEVICE` environment variable to override the resolved device
  name.

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
