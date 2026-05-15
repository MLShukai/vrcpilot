# vrcpilot

**English** | [日本語](README.ja.md)

[![PyPI](https://img.shields.io/pypi/v/vrcpilot?color=blue)](https://pypi.org/project/vrcpilot/)
[![Python](https://img.shields.io/pypi/pyversions/vrcpilot)](https://pypi.org/project/vrcpilot/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Test](https://github.com/MLShukai/vrcpilot/actions/workflows/test.yml/badge.svg)](https://github.com/MLShukai/vrcpilot/actions/workflows/test.yml)
[![Type Check](https://github.com/MLShukai/vrcpilot/actions/workflows/type-check.yaml/badge.svg)](https://github.com/MLShukai/vrcpilot/actions/workflows/type-check.yaml)
[![Format & Lint](https://github.com/MLShukai/vrcpilot/actions/workflows/pre-commit.yml/badge.svg)](https://github.com/MLShukai/vrcpilot/actions/workflows/pre-commit.yml)

Python automation toolkit for the VRChat desktop client on Windows / Linux. It can launch, focus, capture, OCR, detect image templates, and synthesize input through both a typed Python API and the `vrcpilot` CLI.

## Features

- **Process control** — launch VRChat through Steam (`vrcpilot.launch`), detect running PIDs, and terminate the process.
- **Window control** — focus / unfocus the VRChat window and check its foreground state (Win32 / X11 / XWayland).
- **Screen capture** — `Capture` for streaming (mp4 / y4m sinks) and `take_screenshot` for one-off captures that round-trip through YAML.
- **OCR** — pluggable `OCREngine` ABC with the default `RapidOCREngine`. `ocr()` returns word-level results in both window-local and desktop-absolute coordinates.
- **Image-template detection** — `TemplateDetectEngine` using OpenCV `TM_CCOEFF_NORMED`. Detections use the same coordinate schema as OCR.
- **Synthetic input** — keyboard / mouse input via [`pydirectinput`](https://github.com/learncodebygaming/pydirectinput) on Windows and [`inputtino`](https://github.com/games-on-whales/inputtino) + `/dev/uinput` on Linux. Input is sent only while VRChat is focused.
- **Non-ASCII text injection** — `vrcpilot.clipboard` sends arbitrary Unicode strings through clipboard + Ctrl+V.
- **CLI front-end** — subcommands such as `vrcpilot launch / screenshot / ocr / detect / mouse / keyboard / paste / capture / ...`, with tab completion via `argcomplete`.

## Installation

Python 3.12 or later is required.

On Linux, install `inputtino-python` into the same Python environment before installing `vrcpilot`. See the Linux requirements below for the native build packages and `/dev/uinput` permissions. `uv tool install` creates an isolated environment; on Linux, use the `--with inputtino-python` example below.

```bash
# Linux only: install inputtino before vrcpilot
pip install "inputtino-python @ git+https://github.com/games-on-whales/inputtino.git@stable#subdirectory=bindings/python"
```

```bash
# Library + CLI
pip install vrcpilot

# Install with OCR support
pip install "vrcpilot[ocr]"

# Install as an isolated CLI tool
uv tool install vrcpilot

# Install as an isolated CLI tool on Linux
uv tool install --with "inputtino-python @ git+https://github.com/games-on-whales/inputtino.git@stable#subdirectory=bindings/python" vrcpilot

# Install from source for development
git clone https://github.com/MLShukai/vrcpilot
cd vrcpilot
uv sync --all-extras
```

> **Pre-release builds** (`0.X.Yrc1`, `0.X.Ya1`, etc.) are excluded from `pip install` by default. To opt in to a pre-release, use `pip install --pre vrcpilot` or `uv tool install --prerelease=allow vrcpilot` (and the same `--prerelease=allow` flag for the Linux `uv tool install --with inputtino-python` variant above).

## Platform Requirements

### Windows

No additional system packages are required. `pywin32` and `pydirectinput` are installed automatically as dependencies.

### Linux

An X11 or XWayland session is required. Wayland-native sessions are not supported. In that environment, `focus()` / `unfocus()` emit a `RuntimeWarning` and return `False`.

Check your session type with:

```bash
echo $XDG_SESSION_TYPE   # x11 or wayland
echo $DISPLAY            # OK if this has a value, including through XWayland
```

[`inputtino-python`](https://github.com/games-on-whales/inputtino/tree/stable/bindings/python) is built natively from git, so install the following system packages before `pip install`:

```bash
sudo apt-get install -y cmake build-essential pkg-config libevdev-dev
sudo usermod -aG input "$USER"   # write access to /dev/uinput; log out and back in
```

If the `uinput` kernel module is disabled, load it with `sudo modprobe uinput`.

Also note that the distribution name differs from the import name. On PyPI it is `inputtino-python`; in Python, import it as `inputtino`.

### macOS

Not supported.

## Quick Start (CLI)

The CLI is the quickest entry point for driving VRChat. The basic pipeline is: `screenshot` emits a `Screenshot` as YAML, then `ocr` / `detect` consume it from stdin or `--screenshot`.

When using OCR / detect results as click targets, **always use `display_pos.bbox`** (not the window-local `pos`). In multi-monitor environments, or when the window origin is not the top-left corner of the full display, passing `pos` directly will shift the coordinates.

```bash
# Launch VRChat in desktop mode and wait until startup completes
vrcpilot launch --no-vr --screen-width 1280 --screen-height 720 --wait-timeout 60

# Screenshot -> OCR -> save visualization PNG in one line
vrcpilot screenshot | vrcpilot ocr --viz /tmp/viz.png > /tmp/ocr.yaml

# Pass the same pipeline to image-template detection
vrcpilot screenshot | vrcpilot detect -q assets/button.png > /tmp/det.yaml

# Move the mouse and click (desktop-absolute coordinates)
vrcpilot mouse move 1183 514
vrcpilot mouse click left

# Press a key (--duration defaults to 0.1s, the lower bound VRChat reliably accepts)
vrcpilot keyboard press w --duration 1.0

# Input non-ASCII text (clipboard + Ctrl+V)
vrcpilot paste "こんにちは、VRChat！"

# Terminate (idempotent)
vrcpilot terminate
```

See `vrcpilot --help` and `vrcpilot <subcommand> --help` for all options.

## Quick Start (Python API)

```python
from time import sleep

import vrcpilot

# launch() waits up to wait_timeout seconds (default 30s) until VRChat's PID appears.
# None means VRChat was not detected within that time.
pid = vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)
if pid is None:
    raise RuntimeError("VRChat did not start before launch() timed out")
sleep(45)  # extra warm-up wait: shaders / avatar loading / network sync

try:
    # Capture one frame (None on a recoverable failure)
    shot = vrcpilot.take_screenshot()
    if shot is None:
        raise RuntimeError("could not capture the VRChat screen")

    # OCR all visible words (uses a cached RapidOCREngine when engine is omitted)
    result = vrcpilot.ocr(shot)
    for word in result.words:
        print(word.text, result.display_bbox(word))

    # Move the cursor to the center of the first word and left-click
    if result.words:
        x, y, w, h = result.display_bbox(result.words[0])
        vrcpilot.mouse.move(int(x + w / 2), int(y + h / 2))
        vrcpilot.mouse.click(vrcpilot.MouseButton.LEFT)

    # Press a key
    vrcpilot.keyboard.press(vrcpilot.Key.W, duration=1.0)
finally:
    vrcpilot.terminate()
```

## CLI Subcommands

| Subcommand   | Purpose                                                                                               |
| ------------ | ----------------------------------------------------------------------------------------------------- |
| `launch`     | Start VRChat through Steam. Supports `--no-vr`, `--screen-{width,height}`, `--wait-timeout`, and more |
| `pid`        | List running VRChat PIDs, one per line                                                                |
| `terminate`  | Terminate VRChat (idempotent)                                                                         |
| `focus`      | Bring the VRChat window to the foreground                                                             |
| `unfocus`    | Send the VRChat window to the bottom of the z-order                                                   |
| `screenshot` | Capture one frame and emit a `Screenshot` YAML to stdout (PNG path or inline base64)                  |
| `capture`    | Record at a fixed FPS. Saves to file with `-o file.mp4`; otherwise emits y4m to stdout                |
| `mouse`      | `move` / `click` / `scroll` (desktop-absolute coordinates)                                            |
| `keyboard`   | `press` (`--duration` defaults to 0.1s)                                                               |
| `paste`      | Input text through clipboard + Ctrl+V (non-ASCII safe)                                                |
| `ocr`        | Run OCR on a `Screenshot` YAML (stdin pipe or `--screenshot <path>`)                                  |
| `detect`     | Template-search a `Screenshot` YAML with a query image. `-q query.png` / `--threshold` / `--top-k`    |

## Shell Completion

`vrcpilot` supports tab completion through [`argcomplete`](https://pypi.org/project/argcomplete/). The following items can be completed:

- Subcommands (`launch` / `pid` / `terminate` / `focus` / `unfocus` / `screenshot` / `capture` / `mouse` / `keyboard` / `paste` / `ocr` / `detect`)
- Options (`--steam-path`, etc.)
- Options that take file paths (`.exe` for `--steam-path`, `.png` for `--query`, etc.)

### Requirements

- Install for development with `uv sync`, or install with `uv tool install vrcpilot`, and make sure `register-python-argcomplete` is available on PATH.
- If you do not want to add it to your global PATH, replace `register-python-argcomplete ...` in the commands below with `uv run register-python-argcomplete ...`.

### One-Line Setup (Development Repository)

Right after cloning, source / dot-source the bundled bootstrap script if you want to complete "create venv -> activate -> register completion" in one line.

- bash: `. ./clicomp.sh`
- pwsh: `. .\CliComp.ps1`

The script performs the following steps:

1. Activate an existing `.venv`, if present
2. Run `just setup` if `vrcpilot` is not on PATH, then activate again
3. Register `vrcpilot` completion in the current session with `register-python-argcomplete`

If you run it in a subshell, such as `bash clicomp.sh` or `.\CliComp.ps1`, neither the venv nor completion settings will remain in the parent shell. Be sure to source / dot-source it (the script rejects normal execution). To make it persistent, add the following line to your shell startup file.

```bash
# ~/.bashrc
. /path/to/vrcpilot/clicomp.sh
```

```powershell
# $PROFILE
. C:\path\to\vrcpilot\CliComp.ps1
```

### Bash / Git Bash

To enable completion for the current session only:

```bash
eval "$(register-python-argcomplete vrcpilot)"
```

To make it persistent, add the line above to `~/.bashrc` (or `~/.bash_profile` in Git Bash).

### PowerShell

Both Windows PowerShell 5.1 and pwsh 7.x are supported, though pwsh 7.x is recommended for development.

To enable completion for the current session only:

```powershell
register-python-argcomplete --shell powershell vrcpilot | Out-String | Invoke-Expression
```

To make it persistent, add the `Invoke-Expression` line above to your PowerShell profile.

```powershell
code $PROFILE   # notepad $PROFILE is also fine
# Append the Invoke-Expression line above to the end of the file and save it
# Open a new session, or reload with `. $PROFILE`
```

### Troubleshooting

If completion does not work, see the argcomplete documentation: <https://kislyuk.github.io/argcomplete/>.

## Documentation

- **Tutorial / playbook**: [`docs/usage.md`](docs/usage.md) — task-based walkthrough (launch -> observe -> click -> teardown)
- **CLI reference**: [`docs/cli.md`](docs/cli.md) — all subcommands, flags, and exit codes. Same content as `vrcpilot --help` / `vrcpilot <subcommand> --help`
- **Python API reference**: [`docs/python-api.md`](docs/python-api.md) — every symbol exposed as `vrcpilot.<name>`
- **Changelog**: [`CHANGELOG.md`](CHANGELOG.md)
- **Contributing guide**: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## License

Published under the [MIT](LICENSE) license.
