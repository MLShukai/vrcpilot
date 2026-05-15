# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0rc1] - 2026-05-15

Release-candidate cut used to rehearse the end-to-end publish pipeline before the stable `0.1.0` tag.

### Added

- **Tag-driven PyPI publish workflow** (`.github/workflows/publish.yml`) with a Test PyPI -> PyPI -> GitHub Release chain, Trusted Publishing (OIDC), and sigstore signing of built artifacts.
- **Release engineering documentation**: `CONTRIBUTING.md` now codifies the branching, release, hotfix, and pre-release tag conventions, and a new `docs/RELEASE.md` runbook documents the procedure for release engineers.

### Changed

- Version bumped from `0.1.0a1` to `0.1.0rc1` to rehearse the publish pipeline before the stable `0.1.0` tag. No API changes since `0.1.0a1`.

## [0.1.0a1] - 2026-05-06

Initial public alpha release.

### Added

- **Process control**: `vrcpilot.launch`, `vrcpilot.terminate`, `vrcpilot.find_pid`, and `OscConfig`.
- **Window control**: `focus`, `unfocus`, `is_foreground` on Windows (Win32) and Linux (X11 / XWayland).
- **Screen capture**: `Capture` and `CaptureLoop` with `Mp4FrameSink` / `Y4mStdoutFrameSink`; one-shot `take_screenshot` returning a `Screenshot` value object that round-trips through YAML (file-path or inline base64 PNG).
- **OCR**: swappable `OCREngine` ABC with `RapidOCREngine` implementation; `ocr()` consumes a `Screenshot` and returns word-level results with both window-local and desktop-absolute coordinates.
- **Image-template detection**: `DetectEngine` ABC with `TemplateDetectEngine` (OpenCV `TM_CCOEFF_NORMED`); `detect()` returns coordinate-bearing detections with the same coordinate schema as OCR.
- **Synthetic input**: keyboard / mouse via `pydirectinput` (Windows `SendInput`) and `inputtino` (Linux `/dev/uinput`), with VRChat focus-guarding (`ensure_target`, `VRChatNotFocusedError`).
- **Non-ASCII text injection**: `vrcpilot.clipboard` uses pyperclip + Ctrl+V to bypass scancode-keyboard limitations.
- **CLI front-end** (`vrcpilot ...`) covering `launch`, `pid`, `terminate`, `focus`, `unfocus`, `screenshot`, `capture`, `mouse`, `keyboard`, `paste`, `ocr`, and `detect`. The `screenshot` output YAML is the standard hand-off format between subcommands.
- **Shell completion**: argcomplete-driven Tab completion for bash / Git Bash / PowerShell, with `clicomp.sh` / `CliComp.ps1` bootstrap scripts.

### Platforms

- Windows 10 / 11
- Linux with X11 or XWayland sessions (Wayland-native is unsupported; `focus`/`unfocus` warn and return `False`)
- macOS is out of scope.

[0.1.0a1]: https://github.com/MLShukai/vrcpilot/releases/tag/v0.1.0a1
[0.1.0rc1]: https://github.com/MLShukai/vrcpilot/compare/v0.1.0a1...v0.1.0rc1
[unreleased]: https://github.com/MLShukai/vrcpilot/compare/v0.1.0rc1...HEAD
