# Usage Guide

This guide walks through the practical loop for driving VRChat with `vrcpilot`: launch, observe, act, and verify. For flag-by-flag details see [`cli.md`](cli.md); for the equivalent Python API see [`python-api.md`](python-api.md).

The examples target Linux with X11 (or XWayland). The same flow works on Windows after dropping the `.env` setup in [Section 1](#1-load-environment-once-per-shell).

______________________________________________________________________

## 0. Prerequisites checklist

- **VRChat is installed via Steam**, and Steam is logged in.
- **The desktop session is X11 or XWayland.** Run `loginctl show-session "$XDG_SESSION_ID" -p Type` to confirm `Type=x11`. Wayland-native sessions are not supported — `focus()` / `unfocus()` warn and return `False`, and synthetic input cannot reach the window.
- **Steam is already running.** If Steam is not running, `vrcpilot launch` will spend its 30-second wait on Steam's startup screen and then fail with `VRChat PID was not observed before timeout`. Bring Steam up first.
- **Linux only — `inputtino-python` is installed before `vrcpilot`.** The Linux input backend comes from [`inputtino`](https://github.com/games-on-whales/inputtino). Install the native build prerequisites first, then install `inputtino-python` into the same Python environment as `vrcpilot`; see [`README.md` Installation](../README.md#installation).
- **Linux only — write access to `/dev/uinput`.** Synthetic input writes through `/dev/uinput`. Run `sudo usermod -aG input "$USER"`, then log out and back in. Confirm with `groups` showing `input`.
- **The screen is not locked.** Window operations are unstable while the screen is locked.

______________________________________________________________________

## 1. Load environment once per shell

Over SSH, the login shell usually does not have `DISPLAY` or `XAUTHORITY` set. Source them from a `.env` file in the project root for each CLI session:

```bash
set -a && . ./.env && set +a
```

A minimal `.env`:

```
DISPLAY=:0
XAUTHORITY=/home/<you>/.Xauthority
```

The `VIRTUAL_ENV=/usr does not match ... will be ignored` warning from `uv run` is harmless — `uv run` still uses the project `.venv`.

On Windows, no `.env` is needed; the desktop session and the SSH / RDP / local terminal share the same display by default.

______________________________________________________________________

## 2. Launch and warm-up

```bash
vrcpilot launch --no-vr --screen-width 1280 --screen-height 720 --wait-timeout 60
```

- `--no-vr` forces desktop mode. Always pass it on machines without an HMD.
- `--wait-timeout 60` blocks until the VRChat PID is observed, then prints it on stdout. Exit code `0` confirms launch.
- Right after launch, VRChat shows the **Launch Pad** screen with a rotating `01`–`04` icon. This is the menu, not a loading indicator — VRChat may still be busy compiling shaders.
- Allow **about 45 seconds** before sending input. Earlier inputs may race with shader compilation or avatar load.

______________________________________________________________________

## 3. Observe — screenshot, OCR, detect

VRChat is opaque from the outside, so observe before and after every action.

### 3.1 Screenshot

```bash
vrcpilot screenshot -o /tmp/vrc.png > /tmp/vrc.yaml
```

The YAML on stdout records:

- `path` — absolute path to the PNG (file mode), or `image` — base64 PNG (inline mode, when `-o` is omitted).
- `x`, `y` — VRChat window's top-left in desktop-absolute pixels (informational; OCR / detect results below are window-local).
- `width`, `height` — window size in physical pixels.

### 3.2 OCR

`vrcpilot ocr` does not capture the screen itself. Pipe a `Screenshot` YAML into it, or pass `--screenshot <path>`:

```bash
# Inline pipe (shortest)
vrcpilot screenshot | vrcpilot ocr --viz /tmp/viz.png > /tmp/ocr.yaml

# Reuse an existing screenshot YAML
vrcpilot ocr --screenshot /tmp/vrc.yaml > /tmp/ocr.yaml
```

Each `words[i]` carries:

- `text` and `confidence`.
- `pos.{polygon,bbox}` — window-local pixels (origin at the VRChat window's top-left).

`vrcpilot mouse move` interprets its `X Y` arguments in the same window-local frame, so `pos.bbox` feeds in directly — no per-coordinate translation is needed. See [`cli.md` Coordinate system](cli.md#coordinate-system) for the full story.

`--viz [PATH]` produces a PNG with the polygons drawn over the screenshot. Use it to sanity-check OCR output by eye.

### 3.3 Image-template detect

`vrcpilot detect` follows the same input contract as `ocr`. Use a small reference PNG of the UI element you want to find:

```bash
vrcpilot screenshot | vrcpilot detect -q assets/launch-pad.png --threshold 0.85 --top-k 3 > /tmp/det.yaml
```

`detections[i]` carries `confidence`, `scale`, `rotation`, and `pos.{polygon,bbox}` (window-local pixels).

`TM_CCOEFF_NORMED` works best with pixel-perfect crops of static UI elements. For text, prefer OCR.

______________________________________________________________________

## 4. Move and click

```bash
# Replace 600 / 360 with the center of an OCR/detect pos.bbox you obtained above.
vrcpilot mouse move 600 360
vrcpilot mouse click left
```

- Coordinates are **VRChat window-local pixels** — the same frame OCR / detect emit under `pos`. `--rel` switches to a delta from the current cursor position. Coordinates outside the VRChat window are not rejected; they reach the OS as-is.
- `vrcpilot mouse click` defaults to `left` and `--count 1`. Use `--count 2` for double-click; `--duration 0.05` to hold the button briefly.

For paired down/up actions such as dragging, use a single Python process. The synthetic input device is released by the kernel when the CLI process exits, so `mouse press` followed by a separate `mouse release` invocation cannot keep the button held between commands.

______________________________________________________________________

## 5. Keyboard

```bash
vrcpilot keyboard press w --duration 1.0           # walk forward ~1m
vrcpilot keyboard press shift w --duration 1.0     # run forward
vrcpilot keyboard press escape                     # close the topmost dialog
```

- `--duration 0.1` is the lower bound that VRChat reliably sees. Do not lower it further.
- Multiple keys form a chord (down all -> sleep -> up reversed). `shift w` above means "hold shift, tap w, then release both".
- Movement scales with `--duration`. Tune per world.
- Each invocation is a separate process. To hold a key while doing something else, use the Python API: `vrcpilot.keyboard.down(...)` and `vrcpilot.keyboard.up(...)` from the same process.

______________________________________________________________________

## 6. Non-ASCII text

Scancode-based keyboard input cannot type Japanese, emoji, and similar text directly. Use `paste`, which copies to the OS clipboard and then sends Ctrl+V:

```bash
vrcpilot paste "こんにちは、VRChat！"

# Or from stdin
cat msg.txt | vrcpilot paste
```

Click into a text field first so it has keyboard focus, then run `paste`. On Linux without `xclip` / `xsel`, you may see a `pyperclip.PyperclipException`; install one of them.

______________________________________________________________________

## 7. View control

In a world (when no menu is open), the desktop client captures the mouse and lets you turn the camera with cursor motion:

```bash
vrcpilot mouse move 200 0 --rel        # turn right ~200 px worth
vrcpilot mouse move 0 -100 --rel       # look up ~100 px worth
```

When a menu is open, the cursor returns to UI-click mode.

______________________________________________________________________

## 8. Recording video and audio

`vrcpilot record` captures video, audio, or both. File output picks the container from the resolved mode (MP4 for anything with video, WAV for audio only); stdout is always a self-describing Matroska (MKV) byte stream so downstream tools like `ffmpeg` can consume it without extra format flags.

```bash
# Video + audio MP4, 10 seconds
vrcpilot record -o /tmp/vrc.mp4 --duration 10

# Video only
vrcpilot record --video -o /tmp/vrc_video.mp4 --duration 10

# Audio only (VRChat-only — native PipeWire on Linux, proc-tap on Windows / macOS; no system audio either way)
vrcpilot record --audio -o /tmp/vrc_audio.wav --duration 10

# Stream MKV to ffmpeg for re-encoding without temp files
vrcpilot record --duration 5 | ffmpeg -i - -c copy /tmp/vrc.mkv
```

- The extension of `-o PATH` must match the mode (`.mp4` for video / both, `.wav` for audio-only); a mismatch exits `2`.
- `--fps` defaults to 30 and is rejected (exit `2`) when combined with `--audio` alone.
- Omit `--duration` to keep recording until Ctrl+C.

See [`cli.md` record](cli.md#record) for the full flag reference and exit codes.

______________________________________________________________________

## 9. Send audio into VRChat's mic

`vrcpilot mic` plays a float32 PCM stream into a virtual-cable output device. With VRChat configured to use that cable as its mic, anything the CLI plays reaches other players as if you had spoken into a real microphone. The primary use case is hooking an LLM agent's TTS up to VRChat.

### One-time setup (Windows)

1. Install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) and reboot if prompted.
2. Open **Settings → System → Sound** and confirm that the playback device `CABLE Input` and the recording device `CABLE Output` are both listed.
3. In VRChat's **Audio** settings, switch the microphone input to **`CABLE Output (VB-Audio Virtual Cable)`**. `vrcpilot mic` writes to `CABLE Input`, and VRChat reads that audio back through `CABLE Output`.

### One-time setup (Linux)

1. Ensure PipeWire (with `pipewire-pulse`) and `libpulse0` are installed.
   On Debian/Ubuntu: `sudo apt-get install pipewire pipewire-pulse libpulse0`.
2. Register the virtual mic once: `vrcpilot linux-mic register`. This writes
   `~/.config/pipewire/pipewire.conf.d/vrcpilot-mic.conf` and loads the
   `module-null-sink` immediately so the device is usable in the current
   session.
3. In VRChat's **Audio** settings, switch the microphone input to
   **`Monitor of VRCPilot Virtual Mic`**. `vrcpilot mic` writes to
   `VRCPilotMic` (the sink) and VRChat picks up that audio from
   `VRCPilotMic.monitor` (the matching monitor source).

Check the status anytime with `vrcpilot linux-mic status`; remove the
registration with `vrcpilot linux-mic unregister`.

### Smoke test

```bash
vrcpilot mic -i greeting.wav
```

The CLI logs progress (sample rate, etc.) to stderr and blocks until the WAV has finished playing. Stdout is silent so the command can sit downstream of any raw-PCM producer without polluting the byte stream:

```bash
# Decode any audio source to raw s16le and play it through the virtual mic.
ffmpeg -i greeting.mp3 -f s16le -ar 48000 -ac 2 - \
  | vrcpilot mic --format s16le --rate 48000 --channels 2
```

### Stream from an LLM agent

Open a `Mic` once and pump one chunk per `play()` call as the agent produces them. The session keeps a `soundcard` player alive for the duration of the `with` block, so the constructor pays the device-resolution cost once and `play(chunk)` only does a buffer write per iteration.

```python
from collections.abc import Iterator

import numpy as np
from numpy.typing import NDArray

import vrcpilot

def agent_tts_chunks() -> Iterator[NDArray[np.float32]]:
    # Replace with the agent's incremental TTS output.
    for _ in range(10):
        yield np.zeros(4800, dtype=np.float32)  # 100 ms of silence per chunk

with vrcpilot.Mic(sample_rate=48000, channels=1) as mic:  # picks up CABLE Input on Windows, VRCPilotMic on Linux
    for chunk in agent_tts_chunks():
        mic.play(chunk)
```

The chunk shape must match the channel count chosen at construction time (`(N,)` for mono, `(N, channels)` for multi-channel). `play()` blocks if the backend's internal buffer is full, giving the caller natural back-pressure for live streams.

______________________________________________________________________

## 10. Pipeline patterns

### Probe → act → re-probe

```bash
# Snapshot before the action
vrcpilot screenshot -o /tmp/vrc_before.png

# Action
vrcpilot keyboard press escape

# Snapshot after — open in your image viewer to verify
vrcpilot screenshot -o /tmp/vrc_after.png
```

### OCR-driven click

Pipe a screenshot through `ocr`, pick the first match for a word, and click its center. The example uses [mikefarah/yq](https://github.com/mikefarah/yq) v4; with `jq`, replace the filter with `'.words[] | select(.text == "Worlds") | .pos.bbox | @tsv'`.

```bash
read -r x y w h < <(
  vrcpilot screenshot \
    | vrcpilot ocr \
    | yq -r '.words[] | select(.text == "Worlds") | .pos.bbox | join(" ")' \
    | head -n 1
)
vrcpilot mouse move $((x + w / 2)) $((y + h / 2))
vrcpilot mouse click left
```

### One-shot teardown

```bash
(set -a && . ./.env && set +a && \
  vrcpilot terminate && \
  vrcpilot launch --no-vr --screen-width 1280 --screen-height 720 --wait-timeout 60 && \
  sleep 45 && \
  vrcpilot keyboard press escape && \
  vrcpilot screenshot -o /tmp/vrc_menu.png \
    | vrcpilot ocr --viz /tmp/vrc_menu_viz.png > /tmp/vrc_menu.yaml && \
  vrcpilot keyboard press escape && \
  vrcpilot terminate)
```

This launches VRChat, captures and OCRs the Launch Pad, then shuts down — a useful smoke test for an environment.

______________________________________________________________________

## 11. Recovering from common failures

| Symptom                                      | Likely cause                                              | Fix                                                     |
| -------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------- |
| `VRChat PID was not observed before timeout` | Steam is not running, or VRChat install is missing        | Start Steam first; verify the install in Steam library  |
| `vrcpilot focus` exits 1 silently            | Wayland-native session, or VRChat window not yet mapped   | Switch to X11 / XWayland; wait for the warm-up          |
| `VRChatNotFocusedError` from input commands  | The window lost focus right before the call               | Re-focus with `vrcpilot focus`, then retry              |
| Tab key does nothing                         | The 2026-series UI no longer maps Tab to a menu           | Use Escape (Launch Pad) and R (Radial Action Menu)      |
| `keyboard press` ignored                     | `--duration` lowered below `0.1`                          | Restore the default of `0.1` or higher                  |
| `mouse move` lands far from the OCR target   | Treating OCR/detect `pos` as desktop-absolute coordinates | Pass `pos.bbox` directly — `mouse move` is window-local |
| `pyperclip.PyperclipException` on Linux      | No clipboard backend installed                            | `sudo apt-get install xclip` (or `xsel`)                |
| Capture hangs or fails immediately           | Wayland-native session, or screen is locked               | Switch to X11 / XWayland; unlock the screen             |

______________________________________________________________________

## 12. Python equivalents

Everything above has a Python counterpart in [`python-api.md`](python-api.md). The end-to-end flow:

```python
from time import sleep
import vrcpilot

vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)
sleep(45)
try:
    shot = vrcpilot.take_screenshot()
    if shot is None:
        raise RuntimeError("could not capture VRChat")

    result = vrcpilot.ocr(shot)
    target = next((w for w in result.words if w.text == "Worlds"), None)
    if target is not None:
        x, y, w, h = target.bbox
        vrcpilot.mouse.move(int(x + w / 2), int(y + h / 2))
        vrcpilot.mouse.click(vrcpilot.MouseButton.LEFT)

    vrcpilot.keyboard.press(vrcpilot.Key.W, duration=1.0)
finally:
    vrcpilot.terminate()
```

Hold a key or button across multiple actions by using `keyboard.down` / `up` and `mouse.press` / `release` from one Python process. These half-action APIs are intentionally absent from the CLI because each CLI invocation is its own process.
