# Python API Reference

This is a hand-curated reference for every symbol exposed at `vrcpilot.<name>`. For runnable examples see [`usage.md`](usage.md); for the equivalent CLI see [`cli.md`](cli.md). Function signatures match the source as of `0.1.0a1`.

## Conventions

- All `vrcpilot.<name>` symbols are listed in [`src/vrcpilot/__init__.py::__all__`](../src/vrcpilot/__init__.py).
- Module attributes `vrcpilot.keyboard`, `vrcpilot.mouse`, and `vrcpilot.clipboard` are also part of the public surface.
- Most call sites that send synthetic input or interact with the VRChat window expect VRChat to be **running and focused**. That requirement is enforced by [`ensure_target()`](#ensure_target), and the high-level helpers call it for you. The relevant exceptions (`VRChatNotRunningError`, `VRChatNotFocusedError`) are re-raised so callers can recover.
- Coordinate-bearing types (`Screenshot`, `OCRWord`, `OCRResult`, `Detection`, `DetectResult`) keep both window-local (`pos*`) and desktop-absolute (`display_pos*`) views. Always feed `display_pos.bbox` into `mouse.move()` — see [coordinate system](cli.md#coordinate-system).
- Code blocks use `...` as the body of every signature so they paste back cleanly into a Python REPL or stub file.

______________________________________________________________________

## Package metadata

### `vrcpilot.__version__`

Resolved from installed distribution metadata via `importlib.metadata`, so it stays in sync with the package version in `pyproject.toml`.

______________________________________________________________________

## Process control

### `vrcpilot.launch`

```python
def launch(
    *,
    app_id: int = 438100,
    steam_path: Path | None = None,
    no_vr: bool = False,
    screen_width: int | None = None,
    screen_height: int | None = None,
    osc: OscConfig | None = None,
    extra_args: list[str] | None = None,
    wait_timeout: float = 30.0,
    wait_interval: float = 1.0,
) -> int | None: ...
```

Start VRChat through Steam. The new process is detached from the calling process group. After spawning Steam, `launch()` polls [`find_pid()`](#vrcpilotfind_pid) for up to `wait_timeout` seconds (default 30s) and returns the observed PID. Pass `wait_timeout=0` (or any non-positive value) to skip the wait and return immediately. This is useful for "fire and forget" launches where you intend to poll later yourself.

**Returns**: the PID once VRChat is observed, or `None` if `wait_timeout <= 0` or the timeout is exceeded. A `None` return on a positive timeout is *not* an exception — branch on the return value if you need a stricter signal.

`app_id` defaults to VRChat's Steam app id. If you need to reference the constant directly, for example when building a custom launch wrapper, import it from the implementation module: `from vrcpilot.process import VRCHAT_STEAM_APP_ID`.

**Raises**: `SteamNotFoundError` when no Steam executable is found.

### `vrcpilot.terminate`

```python
def terminate(*, timeout: float = 5.0) -> list[int]: ...
```

Force-kill every running VRChat process and wait up to `timeout` seconds for them to exit. Idempotent — returns an empty list when nothing is running.

**Returns**: the PIDs that were signalled.

### `vrcpilot.find_pid`

```python
def find_pid() -> int | None: ...
```

**Returns**: the first running VRChat PID, or `None` when nothing matches.

### `vrcpilot.OscConfig`

```python
@dataclass(frozen=True)
class OscConfig:
    in_port: int = 9000
    out_ip: str = "127.0.0.1"
    out_port: int = 9001

    def to_launch_arg(self) -> str: ...
```

Structured form of VRChat's `--osc=<in>:<ip>:<out>` flag. `to_launch_arg()` renders the single CLI token used at launch.

### `vrcpilot.SteamNotFoundError`

Raised by `launch()` (and the Steam discovery helpers) when no Steam executable can be located.

______________________________________________________________________

## Window control

### `vrcpilot.focus`

```python
def focus() -> bool: ...
```

Bring the VRChat window to the foreground (and de-minimize it if needed).

**Returns**: `True` on success, `False` when VRChat is not running, the window is not mapped, the platform call fails, or the session is Wayland-native.

**Raises**: `NotImplementedError` on platforms other than Windows / Linux.

### `vrcpilot.unfocus`

```python
def unfocus() -> bool: ...
```

Send the VRChat window to the bottom of the z-order without raising any other window. Same return / raise contract as `focus()`.

### `vrcpilot.is_foreground`

```python
def is_foreground() -> bool: ...
```

**Returns**: `True` iff the VRChat window is currently in the foreground.

______________________________________________________________________

## Screen capture

### `vrcpilot.Capture`

```python
class Capture:
    def __init__(self, *, frame_timeout: float = 2.0) -> None: ...
    def read(self) -> np.ndarray: ...
    def close(self) -> None: ...
```

Streaming capture session for the VRChat window. Captures without focus. The internal buffer keeps only the most recent frame, so `read()` always returns "now".

- `read()` returns `(H, W, 3)` `uint8` RGB.
- `close()` is idempotent and never raises.
- Supports `with` (context manager).
- `frame_timeout` is the per-frame wait in seconds; must be `> 0`.

**Raises**:

- `NotImplementedError` on platforms other than Windows / Linux.
- `RuntimeError` when the backend cannot start (VRChat not running, window not mapped, X11 unavailable, WGC session failure, Wayland-native).
- `ValueError` when `frame_timeout <= 0`.

### `vrcpilot.CaptureLoop`

```python
class CaptureLoop:
    def __init__(
        self,
        callback: Callable[[np.ndarray], None],
        *,
        fps: float,
        frame_timeout: float = 2.0,
    ) -> None: ...

    @property
    def is_running(self) -> bool: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
```

Drives a `Capture` on a background thread at a fixed `fps`. Each frame is delivered to `callback` as `(H, W, 3)` `uint8` RGB. Supports `with`.

**Raises**: `ValueError` when `fps` or `frame_timeout` is non-positive; `RuntimeError` when the inner `Capture` cannot start; `NotImplementedError` on unsupported platforms.

The CLI `vrcpilot capture` command uses internal sinks (`Mp4FrameSink`, `Y4mStdoutFrameSink`) on top of `CaptureLoop`. Custom sinks are written by passing your own `callback`.

______________________________________________________________________

## Speaker (audio capture)

Process-isolated audio capture for VRChat. The backend is `proc-tap` (a cross-platform native extension that taps a single PID's audio rather than the whole system mix), so the resulting stream contains **only VRChat's output** — Discord, OBS, other applications are not mixed in. Windows / Linux are stable; macOS is experimental.

The backend produces `float32 (N, CHANNELS)` chunks at 48 kHz stereo. The two built-in sinks (`WavFileSink`, `RawPcmStdoutSink`) consume that float32 layout directly and quantise to signed 16-bit PCM internally on write — callers do not need to convert.

### `vrcpilot.speaker.Speaker`

```python
class Speaker:
    def __init__(self, *, read_timeout: float = 2.0) -> None: ...
    def read(self) -> NDArray[np.float32]: ...
    def close(self) -> None: ...
```

Context-managed capture session. VRChat must already be running when the constructor is called; otherwise `RuntimeError` is raised. Each `read()` returns every sample buffered since the previous call as a `(N, 2)` `float32` ndarray. `N == 0` is a valid "no new audio" signal (returned when `read_timeout` expires on a quiet stream). `close()` is idempotent and never raises. Supports `with`.

**Raises**:

- `RuntimeError` when VRChat is not running or the `proc-tap` backend cannot start.
- `ValueError` when `read_timeout <= 0`.

### `vrcpilot.speaker.SpeakerLoop`

```python
class SpeakerLoop:
    def __init__(
        self,
        callback: AudioCallback,
        *,
        chunk_seconds: float = 0.05,
        read_timeout: float = 2.0,
    ) -> None: ...

    @property
    def is_running(self) -> bool: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
```

Background-thread driver around `Speaker`. Constructs and owns its own `Speaker`, so VRChat must already be running when the loop is instantiated. Each tick drains one chunk and forwards it to `callback`; the worker sleeps `chunk_seconds` between drains (default 50 ms, chosen to match the proc-tap buffer cadence). Empty chunks are forwarded verbatim so consumers can treat them as a "silence tick". Exceptions raised by the callback or by `Speaker.read()` are captured and re-raised on the next `stop()` / `close()` so worker-thread failures are never lost. Supports `with`.

**Raises**: `ValueError` when `chunk_seconds` or `read_timeout` is non-positive; `RuntimeError` from the inner `Speaker`.

### `vrcpilot.speaker.WavFileSink`

```python
class WavFileSink:
    def __init__(self, output_path: Path) -> None: ...

    @property
    def sample_count(self) -> int: ...

    def write(self, frame: NDArray[np.float32]) -> None: ...
    def close(self) -> None: ...
```

Persists `(N, 2)` float32 chunks to a 48 kHz / stereo / 16-bit PCM WAV file. The output format is fixed (mirrors the backend contract) — there is no constructor knob for sample rate or bit depth. Out-of-range samples (outside `[-1.0, 1.0]`) are clipped to the full int16 range before quantisation, so overdriven input saturates rather than wrapping. The constructor opens the underlying `wave` writer eagerly, so the parent directory must already exist; otherwise `FileNotFoundError` propagates. `close()` is idempotent and patches the WAV header with the final payload length. Supports `with`.

**Raises**:

- `RuntimeError` when `write()` is called after `close()`.
- `ValueError` when `frame` is not `(N, 2) float32`.

### `vrcpilot.speaker.RawPcmStdoutSink`

```python
class RawPcmStdoutSink:
    def __init__(self, *, stream: BinaryIO | None = None) -> None: ...

    @property
    def sample_count(self) -> int: ...

    def write(self, frame: NDArray[np.float32]) -> None: ...
    def close(self) -> None: ...
```

Headerless counterpart to `WavFileSink`: emits the same int16 PCM payload directly to a binary stream (`sys.stdout.buffer` by default; tests pass a `BytesIO`). Used by the CLI `vrcpilot record` command's pipe mode. The stream is **not self-describing** — consumers must specify the format explicitly, e.g. `ffmpeg -f s16le -ar 48000 -ac 2 -i - ...`. `close()` flushes the stream but never closes it, because the default target (`sys.stdout`) is owned by the interpreter and must outlive the sink. Supports `with`.

**Raises**: same as `WavFileSink.write`.

### `vrcpilot.speaker.AudioCallback`

```python
type AudioCallback = Callable[[NDArray[np.float32]], None]
```

The chunk-callback signature accepted by `SpeakerLoop`. Each callback invocation receives one `(N, 2) float32` chunk; an `N == 0` chunk is a silence tick.

### End-to-end snippet

```python
import time
from pathlib import Path

from vrcpilot.speaker import SpeakerLoop, WavFileSink

# VRChat must already be running; SpeakerLoop raises RuntimeError otherwise.
with (
    WavFileSink(Path("/tmp/vrc.wav")) as sink,
    SpeakerLoop(sink.write, chunk_seconds=0.05) as loop,
):
    loop.start()
    time.sleep(5.0)
# Leaving the with-blocks flushes the WAV header and releases the proc-tap session.
```

______________________________________________________________________

## Screenshot

### `vrcpilot.Screenshot`

```python
@dataclass(frozen=True, eq=False)
class Screenshot:
    image: NDArray[np.uint8]   # (H, W, 3) uint8 RGB
    x: int                     # window top-left, desktop-absolute
    y: int
    width: int
    height: int
    monitor_index: int         # mss.MSS().monitors index
    captured_at: datetime      # UTC

    def save(self, png_path: Path | None = None) -> str: ...
    @classmethod
    def load(cls, text: str) -> Screenshot: ...
```

Pixel data plus the on-screen geometry needed to translate window-local coordinates back to the desktop. `eq=False` because numpy arrays cannot be compared element-wise in `__eq__`.

`save()` returns a YAML string. When `png_path` is provided the PNG is written there and the YAML stores `path:`; otherwise the YAML embeds the PNG as base64 under `image:`. `load()` restores either form.

### `vrcpilot.take_screenshot`

```python
def take_screenshot(*, settle_seconds: float = 0.05) -> Screenshot | None: ...
```

Focus VRChat, sleep `settle_seconds`, and grab a one-shot capture of the VRChat window only.

**Returns**: a `Screenshot`, or `None` on a recoverable failure (Wayland-native, focus refused, window unmapped, mss error).

**Raises**: `NotImplementedError` on unsupported platforms; `ValueError` when `settle_seconds < 0`.

______________________________________________________________________

## OCR

### `vrcpilot.OCRWord`

```python
@dataclass(frozen=True)
class OCRWord:
    text: str
    polygon: Polygon          # (TL, TR, BR, BL), image-local
    confidence: float         # 0.0–1.0

    @property
    def bbox(self) -> tuple[int, int, int, int]: ...   # (x, y, w, h), axis-aligned
    @property
    def center(self) -> tuple[float, float]: ...
```

### `vrcpilot.OCRResult`

```python
@dataclass(frozen=True, eq=False)
class OCRResult:
    screenshot: Screenshot
    words: tuple[OCRWord, ...]

    def display_polygon(self, word: OCRWord) -> Polygon: ...
    def display_bbox(self, word: OCRWord) -> tuple[int, int, int, int]: ...
```

Bundles a `Screenshot` with the words detected on it. `display_*` shifts a word's window-local coordinates to desktop-absolute space using the `Screenshot`'s `x` / `y`.

### `vrcpilot.OCREngine`

```python
class OCREngine(ABC):
    @abstractmethod
    def recognize(self, image: NDArray[np.uint8]) -> Sequence[OCRWord]: ...
```

Swap in your own backend by implementing this ABC.

### `vrcpilot.RapidOCREngine`

```python
class RapidOCREngine(OCREngine):
    def __init__(self, *, params: dict[str, Any] | None = None) -> None: ...
```

Default backend (PP-OCRv4 via `rapidocr`). It lazy-imports `rapidocr` in the constructor, so the rest of the package remains usable without the `ocr` extra installed.

**Raises**: `ImportError` when `rapidocr` is not installed.

### `vrcpilot.ocr`

```python
def ocr(
    screenshot: Screenshot,
    *,
    engine: OCREngine | None = None,
) -> OCRResult: ...
```

Run OCR on `screenshot`. When `engine` is `None`, a process-cached `RapidOCREngine` instance is used.

> `vrcpilot.ocr` is callable directly (`vrcpilot.ocr(shot)`). The submodule `vrcpilot.ocr` is still accessible via `from vrcpilot.ocr import OCREngine` and similar import-from forms — Python's import machinery resolves these through `sys.modules`, so the function binding does not break submodule access.

______________________________________________________________________

## Image-template detection

### `vrcpilot.Detection`

```python
@dataclass(frozen=True)
class Detection:
    polygon: Polygon
    confidence: float
    scale: float        # 1.0 = same size as the query
    rotation: float     # radians, counter-clockwise positive

    @property
    def bbox(self) -> tuple[int, int, int, int]: ...
    @property
    def center(self) -> tuple[float, float]: ...
```

### `vrcpilot.DetectResult`

```python
@dataclass(frozen=True, eq=False)
class DetectResult:
    screenshot: Screenshot
    query: NDArray[np.uint8]    # (h, w, 3) uint8 RGB
    detections: tuple[Detection, ...]

    def display_polygon(self, det: Detection) -> Polygon: ...
    def display_bbox(self, det: Detection) -> tuple[int, int, int, int]: ...
```

### `vrcpilot.DetectEngine`

```python
class DetectEngine(ABC):
    @abstractmethod
    def detect(
        self,
        image: NDArray[np.uint8],
        query: NDArray[np.uint8],
    ) -> Sequence[Detection]: ...
```

### `vrcpilot.TemplateDetectEngine`

```python
class TemplateDetectEngine(DetectEngine):
    def __init__(
        self,
        *,
        threshold: float = 0.85,
        scales: Sequence[float] = (
            0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.75,
            0.9, 1.0, 1.25, 1.5, 1.8, 2.2, 2.6, 3.0,
        ),
        rotations_deg: Sequence[float] = (0.0,),
        nms_iou: float = 0.3,
        max_results: int = 32,
    ) -> None: ...
```

Multi-scale (and optionally multi-rotation) `cv2.matchTemplate(..., TM_CCOEFF_NORMED)` runner with non-maximum suppression.

### `vrcpilot.detect`

```python
def detect(
    screenshot: Screenshot,
    query: NDArray[np.uint8],
    *,
    engine: DetectEngine | None = None,
) -> DetectResult: ...
```

Run `engine.detect(screenshot.image, query)`. When `engine` is `None`, a process-cached `TemplateDetectEngine` is used.

______________________________________________________________________

## Synthetic input

The `keyboard` and `mouse` modules expose thin singleton objects rather than classes. Call methods on them directly. All methods accept `focus: bool = True`; leave it `True` unless you deliberately want to bypass the VRChat focus guard. The signatures below are written as `def`s for paste-friendliness; in practice you call them as `vrcpilot.keyboard.press(...)` and so on.

### `vrcpilot.Key`

`StrEnum` of every supported key name. Members:

- Letters: `A`–`Z`
- Digits: `NUM_0`–`NUM_9`
- Function keys: `F1`–`F12`
- Modifiers: `SHIFT`, `SHIFT_LEFT`, `SHIFT_RIGHT`, `CTRL`, `CTRL_LEFT`, `CTRL_RIGHT`, `ALT`, `ALT_LEFT`, `ALT_RIGHT`, `WIN`, `WIN_LEFT`, `WIN_RIGHT`
- Navigation: `UP`, `DOWN`, `LEFT`, `RIGHT`, `HOME`, `END`, `PAGE_UP`, `PAGE_DOWN`
- Editing: `BACKSPACE`, `DELETE`, `INSERT`, `TAB`, `ENTER`, `ESCAPE`, `SPACE`
- Punctuation: `MINUS`, `EQUALS`, `LBRACKET`, `RBRACKET`, `BACKSLASH`, `SEMICOLON`, `QUOTE`, `COMMA`, `PERIOD`, `SLASH`, `BACKTICK`

### `vrcpilot.keyboard`

```python
def press(*keys: Key, duration: float = 0.1, focus: bool = True) -> None: ...
def down(*keys: Key, focus: bool = True) -> None: ...
def up(*keys: Key, focus: bool = True) -> None: ...
```

`press` is a chord-tap: keys are pressed left-to-right, held for `duration` seconds, then released right-to-left. Do not lower `duration` below `0.1` — VRChat / Unity drops shorter taps.

`down` and `up` are paired half-actions. They are intentionally useful only within a single Python process; the synthetic input device is released by the kernel when the process exits, so down/up cannot be paired across CLI invocations.

**Raises**: `TypeError` when `keys` is empty; `VRChatNotRunningError` / `VRChatNotFocusedError` from the focus guard.

### `vrcpilot.MouseButton`

`StrEnum` with members `LEFT`, `RIGHT`, `MIDDLE`.

### `vrcpilot.mouse`

```python
def move(x: int, y: int, *, relative: bool = False, focus: bool = True) -> None: ...
def click(*buttons: MouseButton, count: int = 1, duration: float = 0.0, focus: bool = True) -> None: ...
def scroll(amount: int, *, focus: bool = True) -> None: ...
def press(*buttons: MouseButton, focus: bool = True) -> None: ...
def release(*buttons: MouseButton, focus: bool = True) -> None: ...
```

`move(x, y)` defaults to pixels in the virtual-desktop bounding box (`mss.MSS().monitors[0]` on Linux, the Win32 virtual screen on Windows). On standard left-origin monitor layouts this matches "desktop-absolute pixels" and round-trips with `display_pos.bbox` from OCR / detect. If another monitor extends left of the primary, the origin shifts accordingly. With `relative=True`, `(x, y)` is added to the current cursor position.

`click()` falls back to `LEFT` when called with no buttons. `count > 1` repeats the press/release pair. `duration > 0` holds each click for that many seconds.

`press` / `release` are paired half-actions for chord clicks. As with `keyboard.down` / `up`, they are meaningful only within a single Python process.

### `vrcpilot.ensure_target`

```python
def ensure_target() -> None: ...
```

Verify VRChat is running and currently focused, focusing it if necessary. Idempotent. The high-level `keyboard` / `mouse` / `clipboard.paste` calls invoke this for you when `focus=True` (the default).

**Raises**: `NotImplementedError` on Wayland-native; `VRChatNotRunningError`; `VRChatNotFocusedError`.

### `vrcpilot.VRChatNotRunningError`, `vrcpilot.VRChatNotFocusedError`

Raised by `ensure_target()` and the input helpers.

______________________________________________________________________

## Clipboard

### `vrcpilot.clipboard.paste`

```python
def paste(text: str, *, focus: bool = True) -> None: ...
```

Copy `text` to the OS clipboard, then send Ctrl+V to VRChat. Use this for non-ASCII content (Japanese, emoji, etc.) — scancode-based `keyboard.press` cannot type those directly.

**Raises**: `pyperclip.PyperclipException` when no clipboard backend is available (e.g. Linux without `xclip` or `xsel` installed); the focus-guard exceptions when `focus=True`.

______________________________________________________________________

## Type aliases

### `vrcpilot.types.Polygon`

```python
type Polygon = tuple[
    tuple[float, float],  # TL
    tuple[float, float],  # TR
    tuple[float, float],  # BR
    tuple[float, float],  # BL
]
```

The 4-corner polygon shape used by `OCRWord.polygon` and `Detection.polygon`. Coordinates are image-local pixels.

______________________________________________________________________

## End-to-end snippet

```python
from time import sleep

import vrcpilot

# launch() waits up to wait_timeout seconds for VRChat's PID.
# None means the timeout expired before VRChat appeared.
pid = vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)
if pid is None:
    raise RuntimeError("VRChat did not start before launch() timed out")
sleep(45)  # extra warm-up wait: shaders / avatar loading / network sync

try:
    shot = vrcpilot.take_screenshot()
    if shot is None:
        raise RuntimeError("could not capture the VRChat screen")

    result = vrcpilot.ocr(shot)
    for word in result.words:
        print(word.text, result.display_bbox(word), word.confidence)

    if result.words:
        first = result.words[0]
        x, y, w, h = result.display_bbox(first)
        vrcpilot.mouse.move(int(x + w / 2), int(y + h / 2))
        vrcpilot.mouse.click(vrcpilot.MouseButton.LEFT)

    vrcpilot.keyboard.press(vrcpilot.Key.W, duration=1.0)
    vrcpilot.clipboard.paste("こんにちは、VRChat！")
finally:
    vrcpilot.terminate()
```
