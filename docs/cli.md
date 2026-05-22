# CLI Reference

This is the flag-by-flag reference for the `vrcpilot` command. For task-oriented walkthroughs see [`usage.md`](usage.md); for the equivalent Python API see [`python-api.md`](python-api.md).

`vrcpilot --help` and `vrcpilot <subcommand> --help` print the same content at runtime.

## Conventions

- Subcommands return exit code `0` on success and `1` on recoverable failure, with a one-line `vrcpilot: <message>` on stderr. A few commands also use `2` for input-shape errors; those cases are called out below.
- `vrcpilot --version` prints the resolved package version (read via `importlib.metadata` so it stays in sync with `pyproject.toml`).
- The CLI is `argcomplete`-aware (`PYTHON_ARGCOMPLETE_OK` is declared in [`src/vrcpilot/cli/__init__.py`](../src/vrcpilot/cli/__init__.py)). See [`README.md`](../README.md#shell-completion) for setup.

### `Screenshot` YAML hand-off

`ocr` and `detect` do not capture the screen themselves. They consume a `Screenshot` YAML produced by `vrcpilot screenshot`. [`cli/_common.py::resolve_screenshot`](../src/vrcpilot/cli/_common.py) resolves that input in this order:

1. `-s` / `--screenshot <path>` if the flag is set. The file always wins; stdin is not even read in this branch.
2. Stdin, if stdin is **not** a TTY (i.e. piped from `vrcpilot screenshot ...`).
3. Otherwise: print a usage message to stderr and exit `1`.

Both forms are first-class: pipe a fresh capture, or pass a previously saved YAML file.

### Coordinate system

OCR and detect emit one coordinate space per match:

- `pos.{polygon,bbox}` — window-local pixels, origin at the VRChat window's top-left.

`vrcpilot mouse move X Y` interprets `(X, Y)` in the **same window-local frame**, so OCR / detect output and `mouse move` round-trip without any translation. There is no separate desktop-absolute view — the previous `display_pos.{polygon,bbox}` field has been removed.

If you need the desktop-absolute position of the window itself, the `screenshot` YAML still records the window top-left under `x` / `y` (and the monitor index under `monitor_index`).

______________________________________________________________________

## launch

Start VRChat through Steam.

```
vrcpilot launch [--app-id INT] [--steam-path PATH] [--no-vr]
                [--screen-width N] [--screen-height N]
                [--osc-in-port N] [--osc-out-ip STR] [--osc-out-port N]
                [--wait-timeout SECONDS]
```

| Option                   | Default     | Description                                                                               |
| ------------------------ | ----------- | ----------------------------------------------------------------------------------------- |
| `--app-id INT`           | `438100`    | Steam App ID. Override only if testing a non-VRChat VRChat-shaped app.                    |
| `--steam-path PATH`      | auto-detect | Explicit path to `steam.exe` / `steam` binary.                                            |
| `--no-vr`                | off         | Force desktop mode (passes `--no-vr` to VRChat). Use this on machines without an HMD.     |
| `--screen-width N`       | unset       | Pass `-screen-width N` to Unity.                                                          |
| `--screen-height N`      | unset       | Pass `-screen-height N` to Unity.                                                         |
| `--osc-in-port N`        | unset       | Enable OSC; sets the inbound UDP port. The OSC config is only forwarded when this is set. |
| `--osc-out-ip STR`       | `127.0.0.1` | OSC outbound IP (only meaningful with `--osc-in-port`).                                   |
| `--osc-out-port N`       | `9001`      | OSC outbound port (only meaningful with `--osc-in-port`).                                 |
| `--wait-timeout SECONDS` | `30`        | How long to wait for the VRChat PID to appear. `0` returns immediately without waiting.   |

**Output**: when `--wait-timeout > 0` and a PID is observed, that PID is printed on stdout (one line). On Steam-not-found or wait timeout, `vrcpilot: <message>` is written to stderr.

**Exit codes**: `0` on success, `1` on wait-timeout, `2` if Steam cannot be located.

**Side effects**: starts Steam if it is not already running, then launches the requested app.

______________________________________________________________________

## pid

List currently running VRChat process IDs.

```
vrcpilot pid
```

**Output**: one PID per line on stdout. No output when nothing is running.

**Exit codes**: `0` if at least one PID is found, `1` if no VRChat process is running.

**Side effects**: none.

______________________________________________________________________

## terminate

Terminate all running VRChat processes. Idempotent — safe to call when nothing is running.

```
vrcpilot terminate
```

**Output**: PIDs killed, one per line on stdout. Empty when nothing was running.

**Exit codes**: always `0`.

**Side effects**: sends a force-kill signal to each matching process.

______________________________________________________________________

## focus

Bring the VRChat window to the foreground.

```
vrcpilot focus
```

**Output**: silent on success. On failure, `vrcpilot: could not focus VRChat` is written to stderr.

**Exit codes**: `0` on success, `1` on failure (VRChat not running, window not mapped, X11 / Wayland-native unsupported).

**Side effects**: changes the desktop's focused window.

______________________________________________________________________

## unfocus

Send the VRChat window to the bottom of the z-order without raising another specific window.

```
vrcpilot unfocus
```

**Output**: silent on success. On failure, `vrcpilot: could not unfocus VRChat` is written to stderr.

**Exit codes**: `0` on success, `1` on failure.

**Side effects**: rearranges the desktop window stack.

______________________________________________________________________

## screenshot

Take a one-shot capture and emit a `Screenshot` YAML.

```
vrcpilot screenshot [-o PATH]
```

| Option                     | Default | Description                                                                                                                                                           |
| -------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-o PATH`, `--output PATH` | unset   | Write the PNG to `PATH`. The YAML records the absolute path under `path:`. When omitted, the PNG is base64-embedded in the YAML under `image:` (suitable for piping). |

**Output**: a YAML document on stdout with these top-level keys (preserved order, not alphabetical):

- `path` (file mode) or `image` (inline mode)
- `x`, `y`, `width`, `height`
- `monitor_index`
- `captured_at` (ISO-8601 UTC)

**Exit codes**: `0` on success, `1` if capture fails.

**Side effects**: writes a PNG to disk only when `-o` is set. The parent directory of `-o PATH` must already exist; a missing parent currently surfaces as a `FileNotFoundError` traceback rather than a clean exit-1.

______________________________________________________________________

## capture

Record the VRChat window as a video stream.

```
vrcpilot capture [-o PATH] [--fps FLOAT] [--duration SECONDS]
```

| Option                     | Default      | Description                                                                                                                                                                                         |
| -------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-o PATH`, `--output PATH` | stdout (y4m) | If set to an existing directory, files are written as `<dir>/vrcpilot_capture_<UTC>.mp4`. If set to a file path, that path is used as-is (mp4). If unset, a binary y4m stream is written to stdout. |
| `--fps FLOAT`              | `30.0`       | Target frame rate.                                                                                                                                                                                  |
| `--duration SECONDS`       | unbounded    | Stop after this many seconds. Without it, the loop runs until interrupted (Ctrl+C).                                                                                                                 |

**Output**:

- File mode: progress is logged to stderr; on completion, the absolute output path is printed once on stdout.
- Pipe mode: a binary y4m stream is written to stdout; progress is logged to stderr.

**Exit codes**: `0` on success, `1` if no frames were captured or pipe mode is requested while stdout is a TTY.

**Side effects**: writes an mp4 file in file mode.

______________________________________________________________________

## record

Record VRChat-only audio (via `proc-tap` process loopback — system audio from other applications is not mixed in) to a WAV file or as a raw PCM stream.

```
vrcpilot record [-o PATH] [--duration SECONDS]
```

| Option                     | Default        | Description                                                                                                                                                                                                                                                                                               |
| -------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-o PATH`, `--output PATH` | stdout (s16le) | If set to an existing directory, files are written as `<dir>/vrcpilot_record_<YYYYMMDD_HHMMSS>.wav`. If set to any other path, that path is used as-is for the WAV file (no extension forcing). If unset, a raw signed 16-bit little-endian PCM stream (48 kHz, stereo, headerless) is written to stdout. |
| `--duration SECONDS`       | unbounded      | Stop after this many seconds. Without it, recording continues until interrupted (Ctrl+C).                                                                                                                                                                                                                 |

**Output**:

- File mode: progress is logged to stderr; on completion, the absolute path of the saved WAV is printed once on stdout.
- Pipe mode: a binary `s16le` PCM stream is written to stdout; progress is logged to stderr. The stream is **not self-describing** — downstream consumers must specify the format explicitly, e.g. `ffmpeg -f s16le -ar 48000 -ac 2 -i - ...`.

**Exit codes**: `0` on success, `1` if VRChat is not running, no samples were captured, or pipe mode is requested while stdout is a TTY.

**Side effects**: writes a WAV file in file mode (48 kHz / stereo / 16-bit PCM). Acquires a `proc-tap` process-loopback session against the VRChat PID for the duration of the recording.

______________________________________________________________________

## mic

Stream PCM audio into a virtual mic device so VRChat picks it up as microphone input. Symmetric counterpart of `record`: `record` emits WAV / raw `s16le`, and `mic` consumes the same payload — `vrcpilot record -o - | vrcpilot mic` round-trips audio without an intermediate file. Primary use case is feeding an LLM agent's TTS into VRChat.

```
vrcpilot mic [-i PATH] [--device NAME] [--rate HZ] [--channels {1,2}]
             [--format {auto,wav,s16le}] [--chunk-ms MS]
```

| Option                      | Default | Description                                                                                                                                                                                                                  |
| --------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-i PATH`, `--input PATH`   | `-`     | Audio source. `-` reads from stdin. A `.wav` path is decoded with the stdlib `wave` module (16-bit signed PCM required). Any other path needs `--format s16le`.                                                              |
| `--device NAME`             | unset   | Output-device name substring (passed to `soundcard` matching). When unset, falls back to `$VRCPILOT_MIC_DEVICE`, then the OS default (`CABLE Input` on Windows; `VRCPilotMic` on Linux after `vrcpilot linux-mic register`). |
| `--rate HZ`                 | `48000` | Sample rate for raw `s16le` input. Ignored for WAV (the WAV header wins).                                                                                                                                                    |
| `--channels {1,2}`          | `2`     | Channel count for raw `s16le` input. Default is `2` to match `vrcpilot record`'s stereo `s16le` pipe output. Ignored for WAV.                                                                                                |
| `--format {auto,wav,s16le}` | `auto`  | Force input interpretation. `auto` + file → decoded as WAV iff the extension is `.wav` (other extensions exit `2`). `auto` + stdin → raw `s16le` (matches `vrcpilot record`'s pipe mode, which is headerless).               |
| `--chunk-ms MS`             | `100`   | Chunk size in milliseconds for raw `s16le` streaming. Only affects pull cadence; the backend drains across chunks regardless.                                                                                                |

**Input resolution**:

- `-i -` (the default) — read from stdin. Refuses to run if stdin is a TTY (exits `2`) because there is no data to play.
- `-i path.wav` (or any path with `--format wav`) — open as a 16-bit signed PCM WAV file.
- `-i path.raw --format s16le` — open as raw little-endian signed 16-bit PCM at `--rate` / `--channels`.

**Output**: progress messages are written to stderr (sample rate, etc.). Stdout is **silent** so this subcommand can sit downstream of a `record` pipe without polluting its byte stream.

**Exit codes**: `0` on success. `1` for device-lookup failure (`MicDeviceNotFoundError`), unsupported WAV (non-16-bit signed PCM), `soundcard` / libpulse / WASAPI runtime failure, file-open errors, or `soundcard` not installed. `2` for argument-shape errors: `-i -` against a TTY, or `--format auto` against a non-WAV file path.

**Side effects**: opens a `soundcard` output player on the resolved device and writes the float-converted payload to it. On Windows + VB-Cable, this means VRChat (configured to use `CABLE Output` as its mic) receives the audio as if it were live microphone input. On Linux + PipeWire, the audio reaches VRChat through `Monitor of VRCPilot Virtual Mic`.

**Requirements**: on Windows, install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) and switch VRChat's microphone to `CABLE Output`. On Linux, run `vrcpilot linux-mic register` first (this creates the `VRCPilotMic` PipeWire sink) and switch VRChat's microphone to `Monitor of VRCPilot Virtual Mic`; `libpulse0` must also be installed because `soundcard` links against it via CFFI.

**Examples**:

```bash
# Play a WAV file
vrcpilot mic -i greeting.wav

# record -> mic round trip (3 seconds of VRChat audio sent back through the mic)
vrcpilot record -o - --duration 3 | vrcpilot mic --format s16le --channels 2

# Raw PCM file with an explicit format
vrcpilot mic -i tts.raw --format s16le --rate 24000 --channels 1
```

______________________________________________________________________

## linux-mic

Manage the persistent `VRCPilotMic` virtual mic on Linux (PipeWire
`module-null-sink`). Three actions are exposed under the same parent
subparser:

```
vrcpilot linux-mic register [--no-runtime-load]
vrcpilot linux-mic unregister
vrcpilot linux-mic status
```

| Action       | Description                                                                                                                                        |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `register`   | Write the persistent PipeWire config fragment and (by default) load `module-null-sink` now so the sink is usable in the current session.           |
| `unregister` | Remove the config fragment and unload any matching runtime module. Idempotent — exits `0` even when nothing was registered.                        |
| `status`     | Report whether the config is present, whether the runtime module is loaded, and whether `soundcard` can see the device. Always exits `0` on Linux. |

| Option              | Applies to | Default | Description                                                                                                                                  |
| ------------------- | ---------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `--no-runtime-load` | `register` | off     | Skip the immediate `pulsectl` `module_load` step. The persistent config is still written; restart PipeWire to pick it up on a later session. |

**Output**: human-readable progress goes to stderr (config path, runtime
load result, VRChat-side hint). The `status` action additionally writes
a machine-readable summary to stdout with the fixed vocabulary
`config: {present|absent}`, `config_path: <path>`, `runtime: {loaded|not loaded|unavailable}`, and `soundcard: {visible|not visible|unavailable}` (one key per line). `unavailable` is paired with
an `error: <message>` line on stderr describing the underlying probe
failure.

**Exit codes**:

- `0` on success (including `register`/`unregister` when the runtime
  step degrades to a warning, and `status` on any Linux probe outcome).
- `2` on non-Linux platforms — the command short-circuits with a hint
  pointing at VB-Cable for Windows.

**Side effects**: writes / removes
`$XDG_CONFIG_HOME/pipewire/pipewire.conf.d/vrcpilot-mic.conf` (or
`~/.config/...` when the variable is unset). When the runtime load is
enabled, calls `pulsectl.Pulse.module_load("module-null-sink", ...)` —
runtime failures (missing `pulsectl`, control-plane error) degrade to a
warning on stderr without changing the exit code, because the
persistent config is the source of truth.

______________________________________________________________________

## mouse

Send synthetic mouse input to VRChat. All actions guard on VRChat being running and focused.

### `mouse move`

```
vrcpilot mouse move X Y [--rel]
```

| Argument | Description                                                                                                                                                   |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `X`, `Y` | Target position in **VRChat window-local pixels** — same frame as `pos.bbox` from `ocr` / `detect`. See [Coordinate system](#coordinate-system).              |
| `--rel`  | Treat `X`, `Y` as a relative delta from the current cursor position. Coordinates outside the VRChat window are not rejected; they are passed to the OS as-is. |

### `mouse click`

```
vrcpilot mouse click [BUTTON ...] [--count N] [--duration SECONDS]
```

| Argument / Option    | Default | Description                                                                                                                      |
| -------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `BUTTON ...`         | `left`  | One or more of `left`, `right`, `middle`. Multiple buttons are pressed simultaneously.                                           |
| `--count N`          | `1`     | Repeat the click `N` times.                                                                                                      |
| `--duration SECONDS` | `0.0`   | How long to hold the buttons down per click. `0.0` (the default) skips the sleep so the press / release pair fires back-to-back. |

### `mouse scroll`

```
vrcpilot mouse scroll AMOUNT
```

| Argument | Description                                                        |
| -------- | ------------------------------------------------------------------ |
| `AMOUNT` | Vertical scroll units. Positive scrolls down, negative scrolls up. |

**Exit codes** (all `mouse` subcommands): `0` on success, `1` if VRChat is not running or is not focused.

**Side effects**: synthesizes input via [`pydirectinput`](https://github.com/learncodebygaming/pydirectinput) (Windows) or [`inputtino`](https://github.com/games-on-whales/inputtino) (Linux uinput).

> `mouse press` / `mouse release` are intentionally not exposed. The kernel releases buttons when the CLI process exits, so down/up cannot be paired across separate invocations. For paired down/up actions, drive input from a single Python process via [`vrcpilot.mouse.press` / `vrcpilot.mouse.release`](python-api.md#mouse).

______________________________________________________________________

## keyboard

Send a synthetic key-tap (or chord) to VRChat.

```
vrcpilot keyboard press KEY [KEY ...] [--duration SECONDS]
```

| Argument / Option    | Default  | Description                                                                                     |
| -------------------- | -------- | ----------------------------------------------------------------------------------------------- |
| `KEY ...`            | required | One or more key names. Multiple keys form a chord (down all → sleep → up reversed).             |
| `--duration SECONDS` | `0.1`    | Hold time for the whole chord. Do not set this below `0.1` — VRChat / Unity drops shorter taps. |

Valid `KEY` values: `a`–`z`, `0`–`9`, `f1`–`f12`, modifiers (`shift` / `shiftleft` / `shiftright`, `ctrl` / `ctrlleft` / `ctrlright`, `alt` / `altleft` / `altright`, `win` / `winleft` / `winright`), navigation (`up`, `down`, `left`, `right`, `home`, `end`, `pageup`, `pagedown`), editing (`backspace`, `delete`, `insert`, `tab`, `enter`, `escape`, `space`), punctuation (`minus`, `equals`, `lbracket`, `rbracket`, `backslash`, `semicolon`, `quote`, `comma`, `period`, `slash`, `backtick`).

**Exit codes**: `0` on success, `1` if VRChat is not running or is not focused.

**Side effects**: synthesizes input as above.

> `keyboard down` / `keyboard up` are intentionally not exposed, for the same reason as `mouse press` / `mouse release`.

______________________________________________________________________

## paste

Inject arbitrary Unicode text via clipboard + Ctrl+V. Use this for non-ASCII content (Japanese, emoji, etc.) that scancode-based `keyboard press` cannot type directly.

```
vrcpilot paste [TEXT]
```

| Argument            | Description                                                                                                                                                                  |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TEXT` (positional) | The text to paste. Optional. If omitted and stdin is piped, the text is read from stdin; if omitted and stdin is a TTY, the command exits `2` rather than blocking on input. |

**Exit codes**: `0` on success, `1` on a VRChat focus-guard failure or clipboard backend error, `2` if `TEXT` is omitted and stdin is a TTY.

**Side effects**: writes to the OS clipboard, then sends Ctrl+V.

______________________________________________________________________

## ocr

Run OCR over a `Screenshot` YAML.

```
vrcpilot ocr [-s YAML | --screenshot YAML] [--viz [PATH]]
```

| Option                         | Default | Description                                                                                                                                                                                          |
| ------------------------------ | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-s YAML`, `--screenshot YAML` | unset   | Read the `Screenshot` YAML from `YAML`. When set, stdin is ignored even if piped — the file always wins.                                                                                             |
| `--viz [PATH]`                 | off     | When the flag is given without an argument, write the visualization PNG to `./vrcpilot_ocr_viz_<UTC>.png`. With a directory: same filename inside that directory. With a file path: that exact path. |

**Input**: stdin pipe (when stdin is not a TTY) or `--screenshot PATH`. See [Screenshot YAML hand-off](#screenshot-yaml-hand-off).

**Output**: a YAML document on stdout:

- `captured_at` (ISO-8601 UTC)
- `window` — `x`, `y`, `width`, `height`, `monitor_index`
- `words[]` — each entry has `text`, `confidence`, `pos.{polygon,bbox}` (window-local pixels)
- `viz_path` — present only when `--viz` was used

**Exit codes**: `0` on success, `1` if the screenshot input cannot be resolved or OCR fails.

**Side effects**: optionally writes a PNG to disk for visualization.

______________________________________________________________________

## detect

Run image-template detection over a `Screenshot` YAML.

```
vrcpilot detect -q QUERY_PATH [-s YAML | --screenshot YAML]
                [--threshold FLOAT] [--top-k INT] [--viz [PATH]]
```

| Argument / Option              | Default                 | Description                                                                                 |
| ------------------------------ | ----------------------- | ------------------------------------------------------------------------------------------- |
| `-q PATH`, `--query PATH`      | required                | Query image (PNG / JPG).                                                                    |
| `-s YAML`, `--screenshot YAML` | unset                   | Read the `Screenshot` YAML from `YAML`. When set, stdin is ignored even if piped.           |
| `--threshold FLOAT`            | engine default (`0.85`) | `cv2.matchTemplate` (`TM_CCOEFF_NORMED`) cutoff. Range `-1.0`–`1.0`.                        |
| `--top-k INT`                  | unbounded               | Keep only the `K` highest-confidence detections.                                            |
| `--viz [PATH]`                 | off                     | Same semantics as `ocr --viz`, but the default filename is `vrcpilot_detect_viz_<UTC>.png`. |

**Input**: same hand-off rules as `ocr`.

**Output**: a YAML document on stdout:

- `captured_at` (ISO-8601 UTC)
- `window` — `x`, `y`, `width`, `height`, `monitor_index`
- `query` — `path`, `width`, `height`
- `detections[]` — each entry has `confidence`, `scale`, `rotation`, `pos.{polygon,bbox}` (window-local pixels)
- `viz_path` — present only when `--viz` was used

**Exit codes**: `0` on success, `1` if the screenshot input cannot be resolved, the query image cannot be loaded, or detection fails.

**Side effects**: optionally writes a PNG to disk for visualization.
