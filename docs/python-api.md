# Python API Reference

This is a hand-curated reference for every symbol exposed at `vrcpilot.<name>`. For runnable examples see [`usage.md`](usage.md); for the equivalent CLI see [`cli.md`](cli.md). Function signatures match the source as of `0.2.0rc1`.

## Conventions

- All `vrcpilot.<name>` symbols are listed in [`src/vrcpilot/__init__.py::__all__`](../src/vrcpilot/__init__.py).
- Module attributes `vrcpilot.keyboard`, `vrcpilot.mouse`, and `vrcpilot.clipboard` are also part of the public surface.
- Most call sites that send synthetic input or interact with the VRChat window expect VRChat to be **running and focused**. That requirement is enforced by [`ensure_target()`](#ensure_target), and the high-level helpers call it for you. The relevant exceptions (`VRChatNotRunningError`, `VRChatNotFocusedError`) are re-raised so callers can recover.
- Coordinate-bearing types (`OCRWord`, `OCRResult`, `Detection`, `DetectResult`) expose only **window-local** coordinates (`polygon` / `bbox`, origin at the VRChat window's top-left). `mouse.move(x, y)` consumes the same window-local frame, so OCR / detect bboxes feed in directly without translation — see [coordinate system](cli.md#coordinate-system).
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

The CLI `vrcpilot record` command composes `CaptureLoop` (for video) and `SpeakerLoop` (for audio) with internal PyAV-backed muxers (`vrcpilot.cli.record.muxer`, not part of the public surface). Build your own writer by passing a `callback` that consumes `(H, W, 3) uint8` RGB frames — for example wrap PyAV or a `ffmpeg` subprocess to mux into whatever container you need.

______________________________________________________________________

## Speaker (audio capture)

Process-isolated audio capture for VRChat. On Linux the backend is a native PipeWire pipeline (virtual null-sink + `pw-link` + `pw-record`); on Windows and macOS it is `proc-tap`, a cross-platform native extension that taps a single PID's audio rather than the whole system mix. Either way the stream contains **only VRChat's output** — Discord, OBS, and other applications are not mixed in. Windows / Linux are stable; macOS is experimental.

The backend produces `float32 (N, CHANNELS)` chunks at 48 kHz stereo. The CLI `vrcpilot record` command muxes these via internal PyAV-backed writers (`vrcpilot.cli.record.muxer`, not part of the public surface); to persist audio from your own code, feed the chunks into a writer of your choice — for example PyAV (`WAV`, `MP4`, `MKV`, ...) or a `ffmpeg` subprocess. The `(N, 2) float32` layout maps cleanly onto PyAV's planar/packed float frames.

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

### `vrcpilot.speaker.AudioCallback`

```python
type AudioCallback = Callable[[NDArray[np.float32]], None]
```

The chunk-callback signature accepted by `SpeakerLoop`. Each callback invocation receives one `(N, 2) float32` chunk; an `N == 0` chunk is a silence tick.

### End-to-end snippet

`SpeakerLoop` accepts any callable that consumes `(N, 2) float32` chunks. The example below collects everything into a single ndarray; in real code you would instead feed each chunk to a streaming writer (PyAV, a `ffmpeg` subprocess, a network socket, etc.).

```python
import time

import numpy as np
from numpy.typing import NDArray

from vrcpilot.speaker import SpeakerLoop

chunks: list[NDArray[np.float32]] = []

# VRChat must already be running; SpeakerLoop raises RuntimeError otherwise.
with SpeakerLoop(chunks.append, chunk_seconds=0.05) as loop:
    loop.start()
    time.sleep(5.0)

audio = np.concatenate(chunks, axis=0) if chunks else np.empty((0, 2), np.float32)
```

To persist the recording, write `audio` (or each incoming chunk) with PyAV, the standard `wave` module, or the `vrcpilot record` CLI command — see [cli.md record](cli.md#record).

______________________________________________________________________

## Mic (audio playback)

Stream float32 PCM into a virtual-cable output device so it appears to VRChat as live microphone input. The primary use case is piping an LLM agent's TTS chunks directly into VRChat without ever touching a real microphone or an intermediate audio file. The session opens a `soundcard` player in `__init__` and keeps it alive until the instance is closed; `play(chunk)` writes a single chunk per call so callers drive the cadence themselves (`for chunk in tts.stream(): mic.play(chunk)`). On Windows the default device is VB-Audio Virtual Cable's `"CABLE Input"`; on Linux the default is the `"VRCPilotMic"` PipeWire sink created by [`vrcpilot.mic.linux.register_virtual_mic`](#vrcpilotmiclinux) (or by running `vrcpilot linux-mic register`).

### `vrcpilot.Mic`

```python
class Mic:
    def __init__(
        self,
        device: str | None = None,
        *,
        sample_rate: int = 48000,
        channels: int = 1,
    ) -> None: ...

    @property
    def device_name(self) -> str: ...
    @property
    def device_id(self) -> str: ...
    @property
    def sample_rate(self) -> int: ...
    @property
    def channels(self) -> int: ...

    def play(self, chunk: NDArray[np.float32]) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...
```

`device` is matched as a case-insensitive **substring** against the names `soundcard` reports (matching covers both `Speaker.name` and `Speaker.id`, with fuzzy id matching). `None` defers to `$VRCPILOT_MIC_DEVICE`, then to the OS default returned by `default_device_name()`. The constructor resolves the device, opens a `soundcard` player for `(sample_rate, channels)`, and enters it — those values are baked in for the lifetime of the session, so reconfiguring means constructing a new `Mic`.

`device_id` exposes the underlying `soundcard` `Speaker.id` as a string. On Linux this is the PulseAudio sink name (e.g. `"VRCPilotMic"`); on Windows it is the WASAPI device id string surfaced by `soundcard`.

`play(chunk)` writes one float32 array per call. The chunk shape must match the configured channel count (`(N,)` for mono, `(N, channels)` for multi-channel) or `ValueError` is raised. The call blocks if the backend's internal buffer is full, giving the caller natural back-pressure for live TTS streams.

The stream is released by `close()`, by leaving the `with` block, or as a best-effort fallback in `__del__`. Prefer the context manager — `__del__` runs at GC time and cannot be relied on for prompt resource release on every interpreter.

**Raises**:

- `MicDeviceNotFoundError` when no output device matches the resolved name, or no default is configured for this platform.
- `ImportError` when `soundcard` is not installed (the lazy import happens during construction).
- `RuntimeError` from the `soundcard` backend (libpulse on Linux, WASAPI on Windows) when it cannot open the player, or from `play()` after the Mic has been closed.
- `OSError` when the native backend shared library cannot be loaded (e.g. `libpulse0` is missing on Linux).
- `ValueError` when `sample_rate` / `channels` is not strictly positive, or when `play()` receives a non-`float32` chunk, a chunk with `ndim` outside `{1, 2}`, or a chunk whose channel count disagrees with the constructor.

### `vrcpilot.MicDeviceNotFoundError`

`RuntimeError` subclass raised when `soundcard` cannot locate an output device matching the resolved name. The message lists every output device `soundcard` currently sees and includes an OS-specific setup hint (`vrcpilot linux-mic register` on Linux, VB-Cable install link on Windows), which makes mis-named installations easy to diagnose.

### `vrcpilot.mic.default_device_name`

```python
def default_device_name() -> str | None: ...
```

The OS-specific default output-device substring. Returns `"CABLE Input"` on Windows and `"VRCPilotMic"` on Linux (after `vrcpilot linux-mic register`). Returns `None` on other platforms.

### `VRCPILOT_MIC_DEVICE`

Environment variable consulted between the constructor argument and `default_device_name()`. Useful for keeping device names out of source code, or for overriding the Windows default without code changes.

### End-to-end snippets

Play a single preloaded buffer:

```python
import numpy as np
import vrcpilot

samples = np.zeros(48000, dtype=np.float32)  # 1 second of silence
with vrcpilot.Mic(sample_rate=48000, channels=1) as mic:
    mic.play(samples)
```

Stream chunks from a generator (the shape an LLM agent's incremental TTS typically produces):

```python
from collections.abc import Iterator

import numpy as np
from numpy.typing import NDArray

import vrcpilot

def tts_chunks() -> Iterator[NDArray[np.float32]]:
    # Replace with the agent's actual chunk iterator.
    for _ in range(10):
        yield np.zeros(4800, dtype=np.float32)  # 100 ms of silence per chunk

with vrcpilot.Mic(sample_rate=48000, channels=1) as mic:
    for chunk in tts_chunks():
        mic.play(chunk)
```

______________________________________________________________________

## `vrcpilot.mic.linux`

Linux-only helpers that manage the persistent `VRCPilotMic` virtual mic in PipeWire. This is the programmatic counterpart of the `vrcpilot linux-mic` CLI; both write the same config fragment and call the same PulseAudio `module_load` path.

**Importing this submodule on non-Linux platforms raises `RuntimeError` at import time**, so guard accesses with `sys.platform == "linux"` (or import lazily) when writing cross-platform code.

### `vrcpilot.mic.linux.register_virtual_mic`

```python
def register_virtual_mic(*, runtime_load: bool = True) -> RegisterResult: ...
```

Persist the `VRCPilotMic` `module-null-sink` to
`$XDG_CONFIG_HOME/pipewire/pipewire.conf.d/vrcpilot-mic.conf` (falling back to `~/.config/...` when the variable is unset) and, when `runtime_load=True`, additionally call `pulsectl.Pulse.module_load("module-null-sink", ...)` so the sink is usable immediately. The runtime step is best-effort — failures (missing `pulsectl`, control-plane error) are surfaced via `RegisterResult.runtime_warning` rather than raised, because the persistent config is the source of truth and will be picked up after the next PipeWire restart / re-login.

**Returns**: a `RegisterResult` describing what was done.

**Raises**: `OSError` when the persistent config cannot be written (permission errors, filesystem failures).

### `vrcpilot.mic.linux.unregister_virtual_mic`

```python
def unregister_virtual_mic() -> bool: ...
```

Remove the persistent config fragment and unload any currently loaded `VRCPilotMic` `module-null-sink`. Returns `True` if anything was actually removed (config file deleted, runtime module unloaded, or both); `False` when neither artefact existed. Idempotent — safe to call repeatedly.

### `vrcpilot.mic.linux.is_registered`

```python
def is_registered() -> bool: ...
```

Return whether the persistent config fragment exists. Does not consult PulseAudio — use the `vrcpilot linux-mic status` CLI or call `open_pulse_control()` directly to inspect the runtime module list.

### `vrcpilot.mic.linux.RegisterResult`

```python
@dataclass(frozen=True)
class RegisterResult:
    config_path: Path
    created_config: bool
    runtime_loaded: bool
    runtime_warning: str | None
```

Outcome of `register_virtual_mic`:

- `config_path` — absolute path to the persistent config fragment.
- `created_config` — `True` iff the call wrote the file (`False` when it already existed with the expected contents).
- `runtime_loaded` — `True` iff the immediate `pulsectl` `module_load` succeeded. `False` when skipped via `runtime_load=False` or when the runtime step failed (in which case `runtime_warning` is populated).
- `runtime_warning` — human-readable description of the runtime-load failure, or `None` when no failure occurred.

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

Pixel data plus the window's on-screen geometry (`x` / `y` are the window's top-left in desktop-absolute pixels; `monitor_index` records the `mss` monitor the capture came from). OCR / detect results are window-local, so this geometry is informational rather than required for clicking. `eq=False` because numpy arrays cannot be compared element-wise in `__eq__`.

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
```

Bundles a `Screenshot` with the words detected on it. All `OCRWord.polygon` / `OCRWord.bbox` values are **window-local** (origin at the VRChat window's top-left), which is the same frame `mouse.move()` consumes — no translation step is required.

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
```

All `Detection.polygon` / `Detection.bbox` values are **window-local**, matching `OCRResult` and the frame `mouse.move()` accepts.

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

`move(x, y)` interprets `(x, y)` as **VRChat window-local pixels** — `(0, 0)` is the top-left of the VRChat window. This is the same frame `OCRWord.bbox` / `Detection.bbox` use, so OCR / detect results feed in directly. Coordinates outside the window are not rejected; they are translated to the desktop and passed to the OS as-is. With `relative=True`, `(x, y)` is a delta added to the current cursor position (the window-local interpretation does not apply in that branch).

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
        print(word.text, word.bbox, word.confidence)

    if result.words:
        first = result.words[0]
        x, y, w, h = first.bbox
        vrcpilot.mouse.move(int(x + w / 2), int(y + h / 2))
        vrcpilot.mouse.click(vrcpilot.MouseButton.LEFT)

    vrcpilot.keyboard.press(vrcpilot.Key.W, duration=1.0)
    vrcpilot.clipboard.paste("こんにちは、VRChat！")
finally:
    vrcpilot.terminate()
```
