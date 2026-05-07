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
- `x`, `y` — VRChat window's top-left, **desktop-absolute**.
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
- `pos.{polygon,bbox}` — window-local.
- `display_pos.{polygon,bbox}` — desktop-absolute, already shifted by `window.x` / `window.y`.

When passing coordinates to `vrcpilot mouse move`, **always use `display_pos.bbox`**. Window-local `pos` will land in the wrong place on multi-monitor setups or when the VRChat window is not at the desktop origin. Both OCR / detect output and `mouse move` share the same virtual-desktop frame, so coordinates round-trip without manual translation; see [`cli.md` Coordinate system](cli.md#coordinate-system) for the full story.

`--viz [PATH]` produces a PNG with the polygons drawn over the screenshot. Use it to sanity-check OCR output by eye.

### 3.3 Image-template detect

`vrcpilot detect` follows the same input contract as `ocr`. Use a small reference PNG of the UI element you want to find:

```bash
vrcpilot screenshot | vrcpilot detect -q assets/launch-pad.png --threshold 0.85 --top-k 3 > /tmp/det.yaml
```

`detections[i]` carries `confidence`, `scale`, `rotation`, `pos.*`, and `display_pos.*`.

`TM_CCOEFF_NORMED` works best with pixel-perfect crops of static UI elements. For text, prefer OCR.

______________________________________________________________________

## 4. Move and click

```bash
# Replace 1183 / 514 with the center of an OCR/detect display_pos.bbox you obtained above.
vrcpilot mouse move 1183 514
vrcpilot mouse click left
```

- Coordinates default to the virtual-desktop frame (the same one OCR / detect emit under `display_pos`). `--rel` switches to a delta from the current cursor position.
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

## 8. Pipeline patterns

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

Pipe a screenshot through `ocr`, pick the first match for a word, and click its center. The example uses [mikefarah/yq](https://github.com/mikefarah/yq) v4; with `jq`, replace the filter with `'.words[] | select(.text == "Worlds") | .display_pos.bbox | @tsv'`.

```bash
read -r x y w h < <(
  vrcpilot screenshot \
    | vrcpilot ocr \
    | yq -r '.words[] | select(.text == "Worlds") | .display_pos.bbox | join(" ")' \
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

## 9. Recovering from common failures

| Symptom                                      | Likely cause                                            | Fix                                                    |
| -------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------ |
| `VRChat PID was not observed before timeout` | Steam is not running, or VRChat install is missing      | Start Steam first; verify the install in Steam library |
| `vrcpilot focus` exits 1 silently            | Wayland-native session, or VRChat window not yet mapped | Switch to X11 / XWayland; wait for the warm-up         |
| `VRChatNotFocusedError` from input commands  | The window lost focus right before the call             | Re-focus with `vrcpilot focus`, then retry             |
| Tab key does nothing                         | The 2026-series UI no longer maps Tab to a menu         | Use Escape (Launch Pad) and R (Radial Action Menu)     |
| `keyboard press` ignored                     | `--duration` lowered below `0.1`                        | Restore the default of `0.1` or higher                 |
| OCR `pos` lands in the wrong spot            | `pos` is window-local, not desktop-absolute             | Use `display_pos.bbox` instead                         |
| `pyperclip.PyperclipException` on Linux      | No clipboard backend installed                          | `sudo apt-get install xclip` (or `xsel`)               |
| Capture hangs or fails immediately           | Wayland-native session, or screen is locked             | Switch to X11 / XWayland; unlock the screen            |

______________________________________________________________________

## 10. Python equivalents

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
        x, y, w, h = result.display_bbox(target)
        vrcpilot.mouse.move(int(x + w / 2), int(y + h / 2))
        vrcpilot.mouse.click(vrcpilot.MouseButton.LEFT)

    vrcpilot.keyboard.press(vrcpilot.Key.W, duration=1.0)
finally:
    vrcpilot.terminate()
```

Hold a key or button across multiple actions by using `keyboard.down` / `up` and `mouse.press` / `release` from one Python process. These half-action APIs are intentionally absent from the CLI because each CLI invocation is its own process.
