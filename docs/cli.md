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

OCR and detect emit two coordinate spaces per match:

- `pos.{polygon,bbox}` — window-local, origin at the VRChat window's top-left.
- `display_pos.{polygon,bbox}` — desktop-absolute, already shifted by `window.x` / `window.y`.

When feeding coordinates back into `vrcpilot mouse move`, **always use `display_pos.bbox`**. Window-local `pos` will land in the wrong place on multi-monitor setups or whenever the VRChat window is not at `(0, 0)`.

The shared frame for screenshot geometry and `mouse move` is the **virtual-desktop bounding box**: `mss.MSS().monitors[0]` on Linux, and the Win32 virtual screen on Windows. On standard left-origin monitor layouts that box starts at `(0, 0)` and matches the usual "desktop-absolute pixels" intuition. If a secondary monitor extends left of the primary, the origin shifts accordingly. OCR / detect output and `mouse move` use the same frame, so coordinates round-trip without manual translation.

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

## mouse

Send synthetic mouse input to VRChat. All actions guard on VRChat being running and focused.

### `mouse move`

```
vrcpilot mouse move X Y [--rel]
```

| Argument | Description                                                                                                                                                            |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `X`, `Y` | Target position in the virtual-desktop frame (see [Coordinate system](#coordinate-system)). On standard layouts this matches `display_pos.bbox` from `ocr` / `detect`. |
| `--rel`  | Treat `X`, `Y` as a relative delta from the current cursor position.                                                                                                   |

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
- `words[]` — each entry has `text`, `confidence`, `pos.{polygon,bbox}`, `display_pos.{polygon,bbox}`
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
- `detections[]` — each entry has `confidence`, `scale`, `rotation`, `pos.{polygon,bbox}`, `display_pos.{polygon,bbox}`
- `viz_path` — present only when `--viz` was used

**Exit codes**: `0` on success, `1` if the screenshot input cannot be resolved, the query image cannot be loaded, or detection fails.

**Side effects**: optionally writes a PNG to disk for visualization.
