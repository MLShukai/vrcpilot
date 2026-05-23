# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Targeting `0.3.0`. Adds first-class multi-instance VRChat support: every PID-dependent Python API and CLI subcommand now takes an explicit target PID, and `launch()` defaults to spawning the EAC-aware `launch.exe` wrapper directly (Windows: `launch.exe`, Linux: `umu-run launch.exe`) instead of going through Steam.

### Breaking

- **`VRChatNotRunningError` moved to `vrcpilot.process`.** Importing it from `vrcpilot.controls.errors` (or `vrcpilot.controls`) no longer works — there is no alias and no deprecation shim. Migrate to `from vrcpilot.process import VRChatNotRunningError` (or the top-level `from vrcpilot import VRChatNotRunningError`, which still works).
- **`launch()` defaults to direct-spawn**, not Steam. On Windows it spawns `launch.exe` directly; on Linux it spawns `umu-run launch.exe`. The previous behaviour (`steam.exe -applaunch 438100`) is preserved behind the new opt-in `via_steam=True` argument (CLI: `--via-steam`), which refuses to launch when any VRChat process is already running (`VRChatAlreadyRunningError`). Direct-spawn was chosen because `VRChat.exe` cannot be invoked directly without breaking EAC (it falls back to offline mode); `launch.exe` is VRChat's own EAC-aware wrapper.
- **PID-unspecified callers fail loudly under multi-instance.** When two or more VRChat processes are running and a PID-dependent API or CLI subcommand is called without `pid=` / `--pid`, the new `VRChatMultipleInstancesError` (a subclass of `VRChatNotRunningError`, so existing `except VRChatNotRunningError` blocks still trigger) is raised with the candidate PID list. The previous behaviour silently targeted the first PID returned by `psutil.process_iter`, which was unpredictable.
- **`process.py` is now a package.** `vrcpilot/process.py` was split into `vrcpilot/process/__init__.py`, `vrcpilot/process/launch.py`, and `vrcpilot/process/_executable.py`. `from vrcpilot.process import ...` keeps working through the package's re-exports, but any code that imported `vrcpilot.process` expecting a single-file module attribute (e.g. `vrcpilot.process.__file__` pointing at a `.py` file) needs updating.
- **`vrcpilot.process.find_pids()` is now sorted (newest first).** PIDs are returned in descending `psutil.Process.create_time()` order so that "the most recently launched VRChat" is at index 0. This makes diff-based PID detection in `launch()` natural but is a behavioural change for any caller that assumed OS-defined enumeration order.
- **`vrcpilot.process.terminate` became variadic** (`terminate(*pids, timeout=5.0)`). The zero-argument call still kills every VRChat process; the new shape additionally allows partial termination (`terminate(1234, 5678)`) and validates each PID's process name before killing to avoid hitting unrelated processes. On the CLI, `vrcpilot terminate` likewise takes positional `PID...` (`vrcpilot terminate` / `vrcpilot terminate 1234` / `vrcpilot terminate 1234 5678`).
- **`vrcpilot.controls.ensure_target` now returns `int`** (the resolved PID) instead of `None`. Callers that ignored the return value are unaffected.

### Deprecated

- **`vrcpilot.find_pid` / `vrcpilot.process.find_pid`** emit `DeprecationWarning` and will be removed in `0.4.0`. They are now thin wrappers around `find_pids()[0]` and still target the newest VRChat under the new sort order, but the helper is fundamentally ambiguous under multi-instance. Migrate to `find_pids()` (full list), `resolve_pid(pid)` (single resolution with multi-instance diagnostics), or pass `pid=` to the specific API you are calling.

### Added

- **`pid` keyword on every PID-dependent API.** `vrcpilot.window.focus / is_foreground / unfocus`, `vrcpilot.geometry.get_vrchat_window_rect`, `vrcpilot.screenshot.take_screenshot`, `vrcpilot.capture.Capture` / `CaptureLoop`, `vrcpilot.speaker.Speaker` / `SpeakerLoop`, `vrcpilot.controls.mouse.*`, `vrcpilot.controls.keyboard.*`, `vrcpilot.clipboard.paste`, and `vrcpilot.controls.ensure_target` all accept `pid: int | None = None` (keyword-only). Omitted means "resolve via `vrcpilot.process.resolve_pid` (which raises `VRChatMultipleInstancesError` under multi-instance)". For `controls.mouse` / `controls.keyboard`, the hot-loop fast path `focus=False` deliberately skips PID resolution entirely so per-frame call overhead is unchanged.
- **`vrcpilot.process.resolve_pid(pid: int | None) -> int`**: single-PID resolution helper. Pass through an explicit PID, or under `None` consult `find_pids()` and raise `VRChatNotRunningError` (zero) or `VRChatMultipleInstancesError` (two or more). Used internally by every PID-dependent public surface.
- **New exceptions in `vrcpilot.process`** (and re-exported from the top-level package): `VRChatMultipleInstancesError` (subclass of `VRChatNotRunningError`, carries `pids: list[int]`), `VRChatLauncherNotFoundError`, `VRChatAlreadyRunningError`, `UmuLauncherNotFoundError`. `vrcpilot.UmuLauncherNotFoundError.args[0]` includes installation hints for Ubuntu (deb from the [umu-launcher releases page](https://github.com/Open-Wine-Components/umu-launcher/releases/latest)) and a fallback suggestion to use `--via-steam`.
- **Launcher auto-discovery**: `vrcpilot.process.find_vrchat_launcher(override=None)` locates the EAC wrapper `launch.exe` via (1) `override` / `--vrchat-launcher`, (2) `$VRCHAT_LAUNCHER`, (3) Steam `libraryfolders.vdf` lookup (registry on Windows, `~/.steam/steam/steamapps/libraryfolders.vdf` / `~/.local/share/Steam/...` on Linux), (4) standard install paths. `vrcpilot.process.find_umu_launcher(override=None)` resolves `umu-run` from `PATH`. Both are public.
- **`build_vrchat_launch_args(profile=N)`** new keyword: appends VRChat's `--profile=N` argv token (rendered as a single `=`-delimited token, the format VRChat accepts). Emitted after `--osc=...` and before `extra_args` so output remains byte-stable.
- **`vrcpilot.launch()` new options** (keyword-only, in addition to `via_steam`): `vrchat_launcher: Path | None` (override the auto-discovered `launch.exe`), and Linux + direct-spawn-only `wineprefix: Path | None`, `proton_path: Path | None`, `profile: int | None`. `profile=N` auto-generates `~/.local/share/vrcpilot/profiles/N/wineprefix/` (honouring `$XDG_DATA_HOME`) and injects it as `WINEPREFIX` so several VRChat instances can run side-by-side in isolated prefixes / save-data trees. Invalid flag combinations (e.g. `via_steam=True` with any of `wineprefix` / `proton_path` / `profile`, or any of those on Windows) raise `ValueError` at the launch entry point.
- **`vrcpilot.process.wait_for_pid` / `wait_for_no_pid`** now accept a keyword-only `pid: int | None = None` to wait for a specific instance to appear / disappear (via `psutil.pid_exists`) rather than the legacy "any VRChat" semantics.
- **CLI `--pid PID`** on `focus`, `unfocus`, `screenshot`, `record`, `mouse`, `keyboard`, `paste`. Omitted means "auto-resolve"; with multiple VRChat processes running, the command exits 1 with a `vrcpilot: multiple VRChat instances detected (PIDs: ...); pass --pid` diagnostic listing the candidate PIDs.
- **CLI `vrcpilot terminate [PID ...]`**: positional variadic. Zero args still mean "kill every VRChat process" (backwards compatible); one or more PIDs kill exactly those. The command validates each PID's process name and exits 1 on a non-VRChat PID.
- **CLI `vrcpilot launch` new flags**: `--via-steam`, `--vrchat-launcher PATH`, `--wineprefix PATH`, `--proton-path PATH`, `--profile N`. Exit codes: 2 for invalid argument combinations or any launcher-not-found, 3 for `VRChatAlreadyRunningError`. `--profile` rejects negative integers at the argparse layer.
- **Linux pre-flight check in `launch()`**. The direct-spawn path now refuses to spawn when neither `$DISPLAY` nor `$WAYLAND_DISPLAY` is set, raising the new `VRChatDisplayNotAvailableError` (CLI exit 2). Otherwise `umu-run` would hang waiting for a display server (the symptom seen when invoking `vrcpilot launch` over plain SSH). The `via_steam=True` path instead checks that the Steam desktop client process is actually running on the host and raises the new `SteamNotRunningError` (CLI exit 2) when it isn't — `steam.exe -applaunch` cannot start the Steam UI itself. Both checks are Linux-only and skipped on Windows. New helper `vrcpilot.steam.is_steam_running()` is public; `SteamNotRunningError` / `VRChatDisplayNotAvailableError` are re-exported at the top level.

### Changed

- `vrcpilot/process.py` split into a package: `vrcpilot/process/__init__.py` (`find_pids`, `resolve_pid`, `terminate`, `wait_for_pid`, `wait_for_no_pid`, exception hierarchy, constants), `vrcpilot/process/launch.py` (`launch`, `OscConfig`, `build_*`), `vrcpilot/process/_executable.py` (private `find_vrchat_launcher` / `find_umu_launcher` implementation). All public symbols remain importable from `vrcpilot.process`.
- **`launch(profile=N)` / `vrcpilot launch --profile N` is now accepted on Windows as well.** Forwards `--profile=N` to VRChat directly so SaveData / cache folders can be separated per instance. Linux additionally maps the profile to a managed `WINEPREFIX` as before. The combination `--profile` + `--via-steam` is still rejected (Steam-route should carry `--profile` via Steam launch options).
- Linux speaker (`vrcpilot.speaker.linux.PipeWireSpeakerBackend`): node enumeration now filters by `application.process.id` matching the resolved VRChat PID, falling back to the previous name-based heuristic only when `process.id` is unavailable. The `tap.json` state file now records `vrchat_pid` so external janitors can tell which VRChat instance a tap belongs to.

## [0.2.1] - 2026-05-23

### Fixed

- **`vrcpilot linux-mic register` no longer kills PipeWire on 1.0+**. The persistent config fragment at `~/.config/pipewire/pipewire.conf.d/vrcpilot-mic.conf` previously declared the `VRCPilotMic` null-sink via `context.modules` with `name = libpipewire-module-null-sink`. That standalone module was removed in PipeWire 0.3 late / 1.0 (replaced by `module-adapter` driving the built-in `support.null-audio-sink` factory). On 1.0.x hosts (Ubuntu 24.04 ships pipewire 1.0.5) the PipeWire daemon aborted at start-up with `could not load mandatory module "libpipewire-module-null-sink"` → `failed to create context` → exit 254, hit the systemd auto-restart rate-limit (`Start request repeated too quickly`), and stayed dead across reboots — the persistent config kept reintroducing the failure. `pipewire-pulse` survived as a separate unit and answered every client connection (including `pulsectl.Pulse` and Steam) with `Host is down`, so the surface symptom was "PulseAudio is dead and won't come back". `0.2.1` rewrites the fragment in 1.0+ syntax (`context.objects` + `factory = adapter` + `factory.name = support.null-audio-sink`); existing installations need to delete the stale `vrcpilot-mic.conf` (or re-run `vrcpilot linux-mic register`) and `systemctl --user reset-failed pipewire.service pipewire-pulse.service wireplumber.service` to clear the rate-limit before PipeWire will start again.

## [0.2.0] - 2026-05-22

Stable release of the 0.2.x series. The release pipeline rehearsed in `0.2.0rc1` is now promoted to stable; the Python and CLI surfaces are unchanged from the release candidate.

## [0.2.0rc1] - 2026-05-22

### Breaking

- Removed the `vrcpilot capture` subcommand. Its functionality is folded into `vrcpilot record --video` (MP4 file output) and `vrcpilot record --video` without `-o` (self-describing MKV byte stream over stdout). The legacy `y4m` stdout format is gone.
- Removed `vrcpilot.speaker.WavFileSink` and `vrcpilot.speaker.RawPcmStdoutSink` from the public API (they were re-exported by mistake; `vrcpilot.capture.Mp4FrameSink` / `Y4mStdoutFrameSink` were never public). The CLI now uses internal PyAV-backed muxers (`vrcpilot.cli.record.muxer`, intentionally not part of the public surface). Users who composed the old sinks directly should write their own writer on top of `CaptureLoop` / `SpeakerLoop` — see [`docs/python-api.md`](docs/python-api.md).
- **Platform support narrowed to Windows / Linux only.** `import vrcpilot` now raises `ImportError` on any other `sys.platform` (macOS, FreeBSD, etc.) — what used to be a runtime `NotImplementedError` from a backend dispatcher is now a hard import-time failure. Platform implementation files were renamed to `windows.py` / `linux.py` (formerly `win32.py` / `x11.py` / `proctap.py` / `pipewire.py`) and `controls/keyboard` / `controls/mouse` became subpackages (`controls/keyboard/{base,windows,linux}.py`, etc.). The `proc-tap` dependency is now confined to Windows via `sys_platform == 'win32'`. CLI: `vrcpilot linux-mic` is no longer registered as a subcommand on non-Linux hosts.

### Added

- **Audio capture** (`vrcpilot.speaker`): `Speaker` + `SpeakerLoop`
  capture VRChat-only audio via process loopback. Linux uses a native
  PipeWire pipeline (virtual null-sink + `pw-link` + `pw-record`) driven
  by a `pulsectl` control plane; Windows uses the `proc-tap` extension.
  Linux runtime now requires the PipeWire CLIs (`pw-link`, `pw-record`)
  and `libpulse0` — both already pulled in by `pipewire-pulse` on most
  desktops. Windows adds the `proc-tap` dependency via
  `sys_platform == 'win32'`.
- **Virtual mic output** (`vrcpilot.mic`): `Mic` opens a `soundcard`
  player in its constructor for a fixed `(sample_rate, channels)` and
  writes one float32 chunk per `play(chunk)` call, so callers drive the
  cadence (`for chunk in tts.stream(): mic.play(chunk)`). The session is
  released via context manager, explicit `close()`, or the finaliser.
  Windows uses VB-Audio Virtual Cable as the default (`"CABLE Input"`);
  Linux uses `VRCPilotMic` after `vrcpilot linux-mic register`.
- **CLI**: `vrcpilot mic` subcommand. Reads stdin by default (raw s16le
  PCM under `--format auto`, suitable for piping from tools like
  `ffmpeg -f s16le -ar 48000 -ac 2 -`); also accepts `-i path.wav` for
  16-bit signed PCM WAV files, with `--format {auto,wav,s16le}`,
  `--rate`, `--channels`, `--chunk-ms`, and `--device` overrides.
- **CLI**: `vrcpilot linux-mic register / unregister / status`
  subcommand for managing the persistent `VRCPilotMic` PipeWire virtual
  mic on Linux. `register` writes
  `~/.config/pipewire/pipewire.conf.d/vrcpilot-mic.conf` and (unless
  `--no-runtime-load` is passed) loads `module-null-sink` immediately
  so the sink is usable in the current session.
- **Python API**: `vrcpilot.mic.linux.register_virtual_mic`,
  `unregister_virtual_mic`, `is_registered`, and the `RegisterResult`
  dataclass. The submodule is Linux-only and raises `RuntimeError` at
  import time on other platforms.
- `vrcpilot.MicDeviceNotFoundError` raised when `soundcard` cannot find a
  matching output device.
- `VRCPILOT_MIC_DEVICE` environment variable to override the resolved device
  name.
- `vrcpilot record` now records video, audio, or both in a single subcommand. The `--video` / `--audio` flags select the mode (passing both, or neither, records both video and audio). File output is MP4 for video / both modes (`-o file.mp4` or a directory argument) and WAV for audio-only mode (`--audio -o file.wav`); a mismatched extension exits `2`. With `-o` omitted, the recording is streamed to stdout as a self-describing Matroska (MKV) container (libx264 + AAC) regardless of mode, so downstream tools like `ffmpeg -i -` can consume it directly.
- New `--fps FLOAT` flag on `vrcpilot record` (default `30.0`); combining it with `--audio` alone is rejected with exit `2` and `vrcpilot: --fps is not meaningful with --audio (drop --fps or remove --audio)`.

### Changed

- **Virtual mic backend**: replaced `sounddevice` (PortAudio) with
  `soundcard` (libpulse on Linux, WASAPI on Windows). Linux now
  enumerates individual PulseAudio sinks, so `vrcpilot mic` can resolve
  `VRCPilotMic` by name and `vrcpilot.mic.default_device_name()`
  returns `"VRCPilotMic"` on Linux. **Breaking**: `Mic.device_index: int` is replaced by `Mic.device_id: str` (the `soundcard` `Speaker.id`
  -- PulseAudio sink name on Linux, WASAPI device id on Windows). On
  Linux this also adds a `libpulse0` system dependency (already pulled
  in by `pipewire-pulse` on most distros).
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
[0.2.0]: https://github.com/MLShukai/vrcpilot/compare/v0.2.0rc1...v0.2.0
[0.2.0rc1]: https://github.com/MLShukai/vrcpilot/compare/v0.1.0...v0.2.0rc1
[0.2.1]: https://github.com/MLShukai/vrcpilot/compare/v0.2.0...v0.2.1
[unreleased]: https://github.com/MLShukai/vrcpilot/compare/v0.2.1...HEAD
