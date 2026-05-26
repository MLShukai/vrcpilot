# Python API リファレンス

[English](python-api.md) | **日本語**

`vrcpilot.<name>` で公開されているすべてのシンボルを手作業でまとめたリファレンスです。実行可能な例は [`usage.ja.md`](usage.ja.md) を、同等の CLI については [`cli.ja.md`](cli.ja.md) を参照してください。関数シグネチャは `0.2.0rc1` 時点のソースに対応します。

## 規約

- `vrcpilot.<name>` のシンボルはすべて [`src/vrcpilot/__init__.py::__all__`](../src/vrcpilot/__init__.py) に列挙されています。
- モジュール属性 `vrcpilot.keyboard`、`vrcpilot.mouse`、`vrcpilot.clipboard` も公開 API の一部です。
- 合成入力を送ったり VRChat ウィンドウと対話したりする呼び出しのほとんどは、VRChat が**起動中かつフォーカスされている**ことを前提としています。この要件は [`ensure_target()`](#vrcpilotcontrolsensure_target) によって強制され、高レベルヘルパーは内部で呼び出します。関連する例外（`VRChatNotRunningError`、`VRChatNotFocusedError`）は呼び出し側でリカバーできるように再送出されます。
- 座標を持つ型（`OCRWord`、`OCRResult`、`Detection`、`DetectResult`）は **ウィンドウローカル** な座標（`polygon` / `bbox`、原点は VRChat ウィンドウの左上）のみを公開します。`mouse.move(x, y)` も同じウィンドウローカル系を受け取るため、OCR / detect の bbox はそのまま渡せます — [coordinate system](cli.ja.md#coordinate-system) を参照してください。
- コードブロックでは、Python REPL やスタブファイルに貼り付けやすいよう、すべてのシグネチャの本体に `...` を使用しています。

______________________________________________________________________

## パッケージメタデータ

### `vrcpilot.__version__`

`importlib.metadata` 経由でインストール済みディストリビューションのメタデータから解決されるため、`pyproject.toml` のパッケージバージョンと常に同期します。

______________________________________________________________________

## プロセス制御

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

Steam 経由で VRChat を起動します。新しいプロセスは呼び出し側のプロセスグループから切り離されます。Steam を起動した後、`launch()` は最大 `wait_timeout` 秒（デフォルト 30 秒）の間 [`find_pids()`](#vrcpilotfind_pids) をポーリングし、観測した PID を返します。`wait_timeout=0`（または非正の値）を渡すと待機をスキップしてすぐに復帰します。これは、自分で後からポーリングするつもりの「fire and forget」型の起動に便利です。

**Returns**: VRChat が観測された時点での PID、もしくは `wait_timeout <= 0` の場合やタイムアウトを超えた場合は `None`。正のタイムアウトで `None` が返ること自体は例外ではありません — より厳密なシグナルが必要であれば戻り値で分岐してください。

`app_id` はデフォルトで VRChat の Steam app id です。カスタムの起動ラッパーを組み立てる際などにこの定数を直接参照したい場合は、実装モジュールからインポートしてください: `from vrcpilot.process import VRCHAT_STEAM_APP_ID`。

**Raises**: Steam の実行ファイルが見つからない場合は `SteamNotFoundError`。

### `vrcpilot.terminate`

```python
def terminate(*, timeout: float = 5.0) -> list[int]: ...
```

実行中の VRChat プロセスをすべて強制終了し、最大 `timeout` 秒間それらの終了を待ちます。冪等で、何も実行されていない場合は空のリストを返します。

**Returns**: シグナルを送った PID のリスト。

### `vrcpilot.find_pids`

```python
def find_pids() -> list[int]: ...
```

**Returns**: 実行中の全 VRChat プロセスの PID。`psutil.Process.create_time()` の降順（新しいものが先頭）で並びます。VRChat が起動していない場合は空リストになります。

### `vrcpilot.OscConfig`

```python
@dataclass(frozen=True)
class OscConfig:
    in_port: int = 9000
    out_ip: str = "127.0.0.1"
    out_port: int = 9001

    def to_launch_arg(self) -> str: ...
```

VRChat の `--osc=<in>:<ip>:<out>` フラグの構造化表現です。`to_launch_arg()` は起動時に使用される単一の CLI トークンを生成します。

### `vrcpilot.SteamNotFoundError`

Steam の実行ファイルが見つからないときに `launch()`（および Steam 検出ヘルパー）から送出されます。

______________________________________________________________________

## ウィンドウ制御

### `vrcpilot.focus`

```python
def focus() -> bool: ...
```

VRChat ウィンドウを前面に出します（必要に応じて最小化状態も解除します）。

**Returns**: 成功時は `True`。VRChat が起動していない、ウィンドウがマップされていない、プラットフォーム呼び出しが失敗した、または Wayland ネイティブセッションである場合は `False`。

**Raises**: Windows / Linux 以外のプラットフォームでは `NotImplementedError`。

### `vrcpilot.unfocus`

```python
def unfocus() -> bool: ...
```

他のウィンドウを前面に上げることなく VRChat ウィンドウを z オーダーの最下部へ送ります。戻り値と例外の契約は `focus()` と同じです。

### `vrcpilot.is_foreground`

```python
def is_foreground() -> bool: ...
```

**Returns**: VRChat ウィンドウが現在前面にあるときに限り `True`。

______________________________________________________________________

## 画面キャプチャ

### `vrcpilot.capture.Capture`

```python
class Capture:
    def __init__(self, *, frame_timeout: float = 2.0) -> None: ...
    def read(self) -> np.ndarray: ...
    def close(self) -> None: ...
```

VRChat ウィンドウのストリーミングキャプチャセッションです。フォーカスを必要としません。内部バッファは最新フレームのみを保持するため、`read()` は常に「現在」のフレームを返します。

- `read()` は `(H, W, 3)` の `uint8` RGB を返します。
- `close()` は冪等で、例外を投げません。
- `with`（コンテキストマネージャ）に対応しています。
- `frame_timeout` は 1 フレームあたりの待機秒数で、`> 0` でなければなりません。

**Raises**:

- Windows / Linux 以外のプラットフォームでは `NotImplementedError`。
- バックエンドが起動できない場合（VRChat が起動していない、ウィンドウが未マップ、X11 が利用できない、WGC セッション失敗、Wayland ネイティブ）は `RuntimeError`。
- `frame_timeout <= 0` の場合は `ValueError`。

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

バックグラウンドスレッドで `Capture` を一定の `fps` で駆動します。各フレームは `(H, W, 3)` の `uint8` RGB として `callback` に渡されます。`with` に対応しています。

**Raises**: `fps` または `frame_timeout` が非正の場合は `ValueError`。内部の `Capture` が起動できない場合は `RuntimeError`。サポート外のプラットフォームでは `NotImplementedError`。

CLI の `vrcpilot record` コマンドは、内部の PyAV ベースの muxer (`vrcpilot.cli.record.muxer`、公開 API ではありません) を使って `CaptureLoop`（映像用）と `SpeakerLoop`（音声用）を組み合わせています。独自のライターを作るには、`(H, W, 3)` の `uint8` RGB フレームを消費する `callback` を渡してください — 例えば PyAV や `ffmpeg` サブプロセスをラップして、必要な任意のコンテナに mux できます。

______________________________________________________________________

## Speaker（音声キャプチャ）

VRChat のプロセス単位音声キャプチャです。Linux ではバックエンドにネイティブ PipeWire パイプライン（仮想 null-sink + `pw-link` + `pw-record`）を、Windows ではシステム全体のミックスではなく単一の PID の音声をタップするネイティブ拡張 `proc-tap` を使用します。どちらのバックエンドでも、ストリームには **VRChat の出力のみ** が含まれます — Discord、OBS、その他のアプリは混ざりません。`import vrcpilot` はそれ以外の `sys.platform` で `ImportError` を送出するため、他の Speaker バックエンドが届く経路はありません。

バックエンドは 48 kHz ステレオで `float32 (N, CHANNELS)` のチャンクを生成します。CLI の `vrcpilot record` コマンドはこれらを内部の PyAV ベースのライター（`vrcpilot.cli.record.muxer`、公開 API ではありません）で mux しています。独自のコードから音声を永続化するには、任意のライター — 例えば PyAV (`WAV`、`MP4`、`MKV`、…) や `ffmpeg` サブプロセス — にチャンクを流し込んでください。`(N, 2) float32` のレイアウトは PyAV の planar / packed float フレームへ綺麗にマップできます。

### `vrcpilot.speaker.Speaker`

```python
class Speaker:
    def __init__(self, *, read_timeout: float = 2.0) -> None: ...
    def read(self) -> NDArray[np.float32]: ...
    def close(self) -> None: ...
```

コンテキストマネージャ形式のキャプチャセッションです。コンストラクタを呼び出した時点で VRChat が既に起動している必要があり、そうでなければ `RuntimeError` を送出します。各 `read()` は前回の呼び出し以降にバッファされたすべてのサンプルを `(N, 2)` の `float32` ndarray として返します。`N == 0` は有効な「新しい音声なし」シグナルです（静かなストリームで `read_timeout` が満了した場合に返ります）。`close()` は冪等で、例外を投げません。`with` に対応しています。

**Raises**:

- VRChat が起動していない場合や Speaker バックエンド（Linux の PipeWire パイプライン、Windows の `proc-tap`）が起動できない場合は `RuntimeError`。
- `read_timeout <= 0` の場合は `ValueError`。

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

`Speaker` をラップするバックグラウンドスレッドドライバです。自前で `Speaker` を構築・所有するため、ループを生成する時点で VRChat が既に起動している必要があります。各 tick で 1 チャンクを取り出して `callback` に転送し、ワーカーは取得の合間に `chunk_seconds` だけスリープします（デフォルト 50 ms。バックエンドのバッファ周期に合わせて選定）。空チャンクもそのまま転送されるので、コンシューマ側で「沈黙 tick」として扱えます。コールバックや `Speaker.read()` で発生した例外は捕捉され、次の `stop()` / `close()` で再送出されるため、ワーカースレッドの失敗が握り潰されることはありません。`with` に対応しています。

**Raises**: `chunk_seconds` または `read_timeout` が非正の場合は `ValueError`。内部の `Speaker` から `RuntimeError`。

### `vrcpilot.speaker.AudioCallback`

```python
type AudioCallback = Callable[[NDArray[np.float32]], None]
```

`SpeakerLoop` が受け取るチャンクコールバックのシグネチャです。各コールバック呼び出しは `(N, 2) float32` のチャンクを 1 つ受け取ります。`N == 0` のチャンクは沈黙 tick です。

### エンドツーエンドのスニペット

`SpeakerLoop` は `(N, 2) float32` のチャンクを受け取る任意の callable を受け付けます。下の例はすべてを 1 つの ndarray に集めていますが、実コードではむしろ各チャンクをストリーミングライター（PyAV、`ffmpeg` サブプロセス、ネットワークソケットなど）に流し込むことになるでしょう。

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

録音を永続化するには、`audio`（または流れてくる各チャンク）を PyAV や標準の `wave` モジュール、もしくは CLI の `vrcpilot record` コマンドで書き出してください — [cli.ja.md record](cli.ja.md#record) を参照してください。

______________________________________________________________________

## Mic（音声再生）

VRChat にライブマイク入力として認識させるために、float32 PCM を仮想ケーブルの出力デバイスへストリーミングします。主なユースケースは、LLM エージェントの TTS チャンクを実マイクや中間音声ファイルを介さずに VRChat へ直接流し込むことです。セッションは `__init__` で `soundcard` のプレイヤーを開き、インスタンスがクローズされるまで生かし続けます。`play(chunk)` は呼び出しごとに 1 チャンクだけ書き込むので、ペースは呼び出し側が制御します（`for chunk in tts.stream(): mic.play(chunk)`）。Windows ではデフォルトデバイスは VB-Audio Virtual Cable の `"CABLE Input"`、Linux では [`vrcpilot.mic.linux.register_virtual_mic`](#vrcpilotmiclinux)（または `vrcpilot linux-mic register` の実行）で作成される `"VRCPilotMic"` の PipeWire シンクです（複数の AI インスタンスを並列に走らせる場合は、`vrcpilot.mic.linux.register_virtual_mic(suffix=...)` で各インスタンス用の `VRCPilotMic_<suffix>` を別々に登録し、TTS 音声経路を分離できます）。

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

`device` は `soundcard` が報告する名前に対して、大文字小文字を区別しない **部分一致** で照合されます（マッチは `Speaker.name` と `Speaker.id` の両方を見ており、id についてはあいまい一致を行います）。`None` の場合はまず `$VRCPILOT_MIC_DEVICE` が、続いて `default_device_name()` が返す OS のデフォルトが使われます。コンストラクタはデバイスを解決して `(sample_rate, channels)` 用の `soundcard` プレイヤーを開き、そのコンテキストへ入ります — これらの値はセッションの生存期間中固定され、再設定したい場合は新しい `Mic` を構築する必要があります。

`device_id` は内部の `soundcard` の `Speaker.id` を文字列として公開します。Linux ではこれは PulseAudio のシンク名（例: `"VRCPilotMic"`）、Windows では `soundcard` が公開する WASAPI デバイス id 文字列です。

`play(chunk)` は呼び出しごとに float32 配列を 1 つ書き込みます。チャンクの形は構成済みのチャネル数と一致していなければなりません（モノラルは `(N,)`、マルチチャネルは `(N, channels)`）。さもなければ `ValueError` が送出されます。バックエンドの内部バッファが満杯の場合は呼び出しがブロックされ、ライブ TTS ストリーム向けに自然な背圧（バックプレッシャ）が得られます。

ストリームは `close()`、`with` ブロックの抜け出し、もしくはベストエフォートのフォールバックとして `__del__` によって解放されます。コンテキストマネージャを優先してください — `__del__` は GC のタイミングで実行されるため、インタプリタによっては迅速なリソース解放を当てにできません。

**Raises**:

- 解決された名前に一致する出力デバイスがない場合、またはこのプラットフォームのデフォルトが設定されていない場合は `MicDeviceNotFoundError`。
- `soundcard` がインストールされていない場合は `ImportError`（lazy import はコンストラクタ実行時に行われます）。
- `soundcard` バックエンド（Linux では libpulse、Windows では WASAPI）がプレイヤーを開けない場合や、Mic クローズ後の `play()` から `RuntimeError`。
- ネイティブバックエンドの共有ライブラリが読み込めない場合は `OSError`（例: Linux で `libpulse0` が無い場合）。
- `sample_rate` / `channels` が厳密に正でない場合、または `play()` が `float32` でないチャンク、`ndim` が `{1, 2}` の外側のチャンク、コンストラクタと一致しないチャネル数のチャンクを受け取った場合は `ValueError`。

### `vrcpilot.MicDeviceNotFoundError`

`RuntimeError` のサブクラスで、`soundcard` が解決された名前に一致する出力デバイスを見つけられない場合に送出されます。メッセージには `soundcard` が現在認識しているすべての出力デバイスと、OS 別のセットアップヒント（Linux では `vrcpilot linux-mic register`、Windows では VB-Cable のインストールリンク）が含まれており、インストール名の取り違いを診断しやすくなっています。

### `vrcpilot.mic.default_device_name`

```python
def default_device_name() -> str | None: ...
```

OS 別の既定出力デバイス部分文字列です。Windows では `"CABLE Input"`、Linux では（`vrcpilot linux-mic register` 実行後に）`"VRCPilotMic"` を返します。それ以外のプラットフォームでは `None` を返します。`vrcpilot linux-mic register --suffix <name>`（または `vrcpilot.mic.linux.register_virtual_mic(suffix="<name>")`）で派生シンクを追加した場合は、`Mic("VRCPilotMic_<name>")` のようにシンク名を直接指定してください — `default_device_name()` は空 suffix の `"VRCPilotMic"` のみを返します。

### `VRCPILOT_MIC_DEVICE`

コンストラクタ引数と `default_device_name()` の間に参照される環境変数です。デバイス名をソースコードに埋め込みたくない場合や、Windows のデフォルトをコード変更なしで上書きしたい場合に便利です。

### エンドツーエンドのスニペット

事前にロードしたバッファを 1 つ再生します:

```python
import numpy as np
import vrcpilot

samples = np.zeros(48000, dtype=np.float32)  # 1 second of silence
with vrcpilot.Mic(sample_rate=48000, channels=1) as mic:
    mic.play(samples)
```

ジェネレータからチャンクをストリーミングします（LLM エージェントのインクリメンタル TTS が典型的に生成する形）:

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

PipeWire 上の永続的な `VRCPilotMic` 仮想マイクを管理する Linux 専用ヘルパーです。これは `vrcpilot linux-mic` CLI のプログラム上の対応物で、両者は同じ config 断片を書き込み、同じ PulseAudio の `module_load` 経路を呼び出します。

すべての公開関数は `suffix` キーワード引数を受け取り、同じ仕組みで複数のシンクを並列管理できます — 主な用途は、複数の AI インスタンスを同時に走らせるときに各インスタンスへ独立した仮想マイクを割り当てることです。空 suffix (`""`、既定) は従来の `VRCPilotMic` を対象にして後方互換を保ち、非空 suffix（例: `"alt"`）は `VRCPilotMic_<suffix>` 派生シンクを対象にします。`suffix` に使える文字は `[A-Za-z0-9_-]` のみで、それ以外を渡すと `ValueError` が送出されます。

**Linux 以外のプラットフォームでこのサブモジュールをインポートすると、インポート時点で `ImportError` が送出されます**（`raise ImportError("vrcpilot.mic.linux is Linux-only")`）。クロスプラットフォームなコードを書く際は `sys.platform == "linux"` でガードする（または遅延 import する）ようにしてください。

### `vrcpilot.mic.linux.register_virtual_mic`

```python
def register_virtual_mic(
    *,
    suffix: str = "",
    runtime_load: bool = True,
) -> RegisterResult: ...
```

`VRCPilotMic`（または `VRCPilotMic_<suffix>`）の `module-null-sink` を
`$XDG_CONFIG_HOME/pipewire/pipewire.conf.d/vrcpilot-mic[-<suffix>].conf`（変数が未設定の場合は `~/.config/...` にフォールバック）へ永続化します。さらに `runtime_load=True` のときは `pulsectl.Pulse.module_load("module-null-sink", ...)` を呼び出してシンクを即座に使えるようにします。ランタイムステップはベストエフォートで、失敗（`pulsectl` 不在、コントロールプレーンのエラー）は `RegisterResult.runtime_warning` に格納されて返り、例外としては送出されません — 永続的な config が正なので、次回の PipeWire 再起動 / 再ログイン後には拾われます。

`suffix` は対象シンクを切り替えます。空 suffix（既定）は既存の `VRCPilotMic` を、非空 suffix は `VRCPilotMic_<suffix>` を対象にします。同じ suffix への再呼び出しは冪等で、既存のランタイムモジュールがあれば一度アンロードしてから読み直すため、二重スタックは起きません。

**Returns**: 行った内容を表す `RegisterResult`。

**Raises**: 永続的な config が書き込めない場合（権限エラー、ファイルシステムの失敗）は `OSError`。`suffix` に不正文字が含まれる場合は `ValueError`。

### `vrcpilot.mic.linux.unregister_virtual_mic`

```python
def unregister_virtual_mic(*, suffix: str = "") -> bool: ...
```

`suffix` に対応する永続的な config 断片を削除し、現在読み込まれている同名 `module-null-sink` をアンロードします。空 suffix（既定）は `VRCPilotMic` を、非空 suffix は `VRCPilotMic_<suffix>` を対象とします。実際に何かが削除された場合（config ファイルの削除、ランタイムモジュールのアンロード、もしくはその両方）は `True` を、どちらの成果物も存在しなかった場合は `False` を返します。冪等で、繰り返し呼んでも安全です。

**Raises**: `suffix` に不正文字が含まれる場合は `ValueError`。

### `vrcpilot.mic.linux.is_registered`

```python
def is_registered(*, suffix: str = "") -> bool: ...
```

`suffix` に対応する永続的な config 断片が存在するかどうかを返します。空 suffix は既定の `VRCPilotMic` を、非空 suffix は `VRCPilotMic_<suffix>` を確認します。PulseAudio は参照しません — ランタイムのモジュール一覧を確認したい場合は `vrcpilot linux-mic status` CLI を使うか、`open_pulse_control()` を直接呼び出してください。

**Raises**: `suffix` に不正文字が含まれる場合は `ValueError`。

### `vrcpilot.mic.linux.config_path`

```python
def config_path(*, suffix: str = "") -> Path: ...
```

`suffix` に対応する PipeWire config 断片の絶対パスを返します（空 suffix は `vrcpilot-mic.conf`、非空 suffix は `vrcpilot-mic-<suffix>.conf`）。`$XDG_CONFIG_HOME` を尊重し、未設定なら `~/.config` にフォールバックします。`vrcpilot linux-mic status` CLI で位置を表示できるよう公開されています。

**Raises**: `suffix` に不正文字が含まれる場合は `ValueError`。

### `vrcpilot.mic.linux.iter_registered_suffixes`

```python
def iter_registered_suffixes() -> list[str]: ...
```

`pipewire.conf.d/` 配下の `vrcpilot-mic*.conf` 断片を走査し、ファイル名から復元した suffix のリストを返します。空 suffix（既定シンク）が先頭、残りは辞書順でソートされるため、CLI 表示や e2e の列挙が安定します。config ディレクトリがまだ存在しない場合は空リスト `[]` を返します。

### `vrcpilot.mic.linux.RegisterResult`

```python
@dataclass(frozen=True)
class RegisterResult:
    config_path: Path
    created_config: bool
    runtime_loaded: bool
    runtime_warning: str | None
    suffix: str
```

`register_virtual_mic` の結果:

- `config_path` — 永続的な config 断片の絶対パス。
- `created_config` — 呼び出しがファイルを書き込んだ場合に限り `True`（期待した内容で既に存在した場合は `False`）。
- `runtime_loaded` — 即時実行された `pulsectl` の `module_load` が成功した場合に限り `True`。`runtime_load=False` でスキップされた場合や、ランタイムステップが失敗した場合は `False`（その場合 `runtime_warning` が設定されます）。
- `runtime_warning` — ランタイムロード失敗の人間可読な説明、もしくは失敗がなかった場合は `None`。
- `suffix` — 登録された suffix を正規化した文字列（既定シンクの場合は空文字列）。呼び出し時に `register_virtual_mic(suffix=...)` へ渡した値がそのまま round-trip されます。

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

ピクセルデータに加え、ウィンドウの画面上ジオメトリ（`x` / `y` はウィンドウの左上のデスクトップ絶対ピクセル、`monitor_index` はキャプチャ元の `mss` モニタ）を保持します。OCR / detect の結果はウィンドウローカルであるため、このジオメトリはクリックに必須ではなく参考情報です。`eq=False` なのは、numpy 配列を `__eq__` で要素ごとに比較できないためです。

`save()` は YAML 文字列を返します。`png_path` が与えられた場合は PNG をそこに書き込み、YAML には `path:` を格納します。さもなければ YAML が PNG を `image:` 下に base64 で埋め込みます。`load()` はいずれの形式も復元します。

### `vrcpilot.take_screenshot`

```python
def take_screenshot(*, settle_seconds: float = 0.05) -> Screenshot | None: ...
```

VRChat をフォーカスし、`settle_seconds` だけスリープしたうえで、VRChat ウィンドウのみのワンショットキャプチャを取得します。

**Returns**: `Screenshot`、もしくはリカバー可能な失敗（Wayland ネイティブ、フォーカス拒否、ウィンドウ未マップ、mss エラー）の場合は `None`。

**Raises**: サポート外のプラットフォームでは `NotImplementedError`。`settle_seconds < 0` の場合は `ValueError`。

______________________________________________________________________

## OCR

### `vrcpilot.ocr.OCRWord`

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

### `vrcpilot.ocr.OCRResult`

```python
@dataclass(frozen=True, eq=False)
class OCRResult:
    screenshot: Screenshot
    words: tuple[OCRWord, ...]
```

`Screenshot` と、その上で検出された単語群をまとめます。すべての `OCRWord.polygon` / `OCRWord.bbox` の値は **ウィンドウローカル**（原点は VRChat ウィンドウの左上）で、これは `mouse.move()` が受け取る座標系と同じです — 変換ステップは不要です。

### `vrcpilot.ocr.OCREngine`

```python
class OCREngine(ABC):
    @abstractmethod
    def recognize(self, image: NDArray[np.uint8]) -> Sequence[OCRWord]: ...
```

この ABC を実装すれば、独自のバックエンドに差し替えられます。

### `vrcpilot.ocr.RapidOCREngine`

```python
class RapidOCREngine(OCREngine):
    def __init__(self, *, params: dict[str, Any] | None = None) -> None: ...
```

デフォルトのバックエンドです（`rapidocr` 経由の PP-OCRv4）。コンストラクタで `rapidocr` を lazy import するため、`ocr` extra をインストールしていなくてもパッケージの他の部分は使えます。

**Raises**: `rapidocr` がインストールされていない場合は `ImportError`。

### `vrcpilot.ocr`

```python
def ocr(
    screenshot: Screenshot,
    *,
    engine: OCREngine | None = None,
) -> OCRResult: ...
```

`screenshot` に対して OCR を実行します。`engine` が `None` の場合、プロセスキャッシュ済みの `RapidOCREngine` インスタンスが使用されます。

> `vrcpilot.ocr` は直接呼び出し可能です（`vrcpilot.ocr(shot)`）。サブモジュールの `vrcpilot.ocr` も `from vrcpilot.ocr import OCREngine` のような import-from 形式で引き続きアクセスできます — Python の import 機構は `sys.modules` を介してこれらを解決するため、関数バインディングがサブモジュールアクセスを壊すことはありません。

______________________________________________________________________

## 画像テンプレート検出

### `vrcpilot.detect.Detection`

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

### `vrcpilot.detect.DetectResult`

```python
@dataclass(frozen=True, eq=False)
class DetectResult:
    screenshot: Screenshot
    query: NDArray[np.uint8]    # (h, w, 3) uint8 RGB
    detections: tuple[Detection, ...]
```

すべての `Detection.polygon` / `Detection.bbox` の値は **ウィンドウローカル** で、`OCRResult` および `mouse.move()` が受け取る座標系と一致しています。

### `vrcpilot.detect.DetectEngine`

```python
class DetectEngine(ABC):
    @abstractmethod
    def detect(
        self,
        image: NDArray[np.uint8],
        query: NDArray[np.uint8],
    ) -> Sequence[Detection]: ...
```

### `vrcpilot.detect.TemplateDetectEngine`

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

非極大抑制を備えた、マルチスケール（オプションでマルチ回転）の `cv2.matchTemplate(..., TM_CCOEFF_NORMED)` ランナーです。

### `vrcpilot.detect`

```python
def detect(
    screenshot: Screenshot,
    query: NDArray[np.uint8],
    *,
    engine: DetectEngine | None = None,
) -> DetectResult: ...
```

`engine.detect(screenshot.image, query)` を実行します。`engine` が `None` の場合、プロセスキャッシュ済みの `TemplateDetectEngine` が使用されます。

______________________________________________________________________

## 合成入力

`keyboard` および `mouse` モジュールは、クラスではなく薄いシングルトンオブジェクトを公開します。これらに対してメソッドを直接呼び出してください。すべてのメソッドは `focus: bool = True` を受け取ります。VRChat フォーカスガードを意図的にバイパスしたい場合を除き、`True` のままにしてください。下に挙げるシグネチャは貼り付けやすさのために `def` で書いていますが、実際には `vrcpilot.keyboard.press(...)` のように呼び出します。

### `vrcpilot.Key`

サポートされる各キー名の `StrEnum` です。メンバ:

- 文字: `A`–`Z`
- 数字: `NUM_0`–`NUM_9`
- ファンクションキー: `F1`–`F12`
- 修飾キー: `SHIFT`, `SHIFT_LEFT`, `SHIFT_RIGHT`, `CTRL`, `CTRL_LEFT`, `CTRL_RIGHT`, `ALT`, `ALT_LEFT`, `ALT_RIGHT`, `WIN`, `WIN_LEFT`, `WIN_RIGHT`
- ナビゲーション: `UP`, `DOWN`, `LEFT`, `RIGHT`, `HOME`, `END`, `PAGE_UP`, `PAGE_DOWN`
- 編集: `BACKSPACE`, `DELETE`, `INSERT`, `TAB`, `ENTER`, `ESCAPE`, `SPACE`
- 記号: `MINUS`, `EQUALS`, `LBRACKET`, `RBRACKET`, `BACKSLASH`, `SEMICOLON`, `QUOTE`, `COMMA`, `PERIOD`, `SLASH`, `BACKTICK`

### `vrcpilot.keyboard`

```python
def press(*keys: Key, duration: float = 0.1, focus: bool = True) -> None: ...
def down(*keys: Key, focus: bool = True) -> None: ...
def up(*keys: Key, focus: bool = True) -> None: ...
```

`press` はコードタップです: キーは左から右へ押下され、`duration` 秒間ホールドされてから、右から左へ離されます。`duration` を `0.1` より下げないでください — VRChat / Unity はそれより短いタップを取りこぼします。

`down` と `up` は対になる半アクションです。これらは意図的に、単一の Python プロセス内でのみ有用となるようにしています。合成入力デバイスはプロセス終了時にカーネルから解放されるため、CLI 呼び出しを跨いで down / up を対にすることはできません。

**Raises**: `keys` が空の場合は `TypeError`。フォーカスガードからの `VRChatNotRunningError` / `VRChatNotFocusedError`。

### `vrcpilot.MouseButton`

`StrEnum` で、メンバは `LEFT`、`RIGHT`、`MIDDLE` です。

### `vrcpilot.mouse`

```python
def move(x: int, y: int, *, relative: bool = False, focus: bool = True) -> None: ...
def click(*buttons: MouseButton, count: int = 1, duration: float = 0.0, focus: bool = True) -> None: ...
def scroll(amount: int, *, focus: bool = True) -> None: ...
def press(*buttons: MouseButton, focus: bool = True) -> None: ...
def release(*buttons: MouseButton, focus: bool = True) -> None: ...
```

`move(x, y)` は `(x, y)` を **VRChat ウィンドウローカルのピクセル** として解釈します — `(0, 0)` は VRChat ウィンドウの左上です。これは `OCRWord.bbox` / `Detection.bbox` が使う座標系と同じであり、OCR / detect の結果をそのまま渡せます。ウィンドウ外の座標は拒否されません。デスクトップ座標へ変換され、そのまま OS に渡されます。`relative=True` の場合、`(x, y)` は現在のカーソル位置に加算されるデルタです（このブランチではウィンドウローカル解釈は適用されません）。

`click()` は引数なしで呼ばれた場合 `LEFT` にフォールバックします。`count > 1` は押下／離上のペアを繰り返します。`duration > 0` は各クリックをその秒数だけ保持します。

`press` / `release` はコードクリック用の対になる半アクションです。`keyboard.down` / `up` と同様に、単一の Python プロセス内でのみ意味があります。

### `vrcpilot.controls.ensure_target`

```python
def ensure_target() -> None: ...
```

VRChat が起動中かつ現在フォーカスされていることを検証し、必要に応じてフォーカスを当てます。冪等です。`focus=True`（デフォルト）のとき、高レベルの `keyboard` / `mouse` / `clipboard.paste` 呼び出しが内部でこれを呼び出します。

**Raises**: Wayland ネイティブでは `NotImplementedError`。`VRChatNotRunningError`、`VRChatNotFocusedError`。

### `vrcpilot.VRChatNotRunningError`, `vrcpilot.VRChatNotFocusedError`

`ensure_target()` と入力ヘルパーから送出されます。

______________________________________________________________________

## クリップボード

### `vrcpilot.clipboard.paste`

```python
def paste(text: str, *, focus: bool = True) -> None: ...
```

`text` を OS のクリップボードへコピーし、続いて VRChat に Ctrl+V を送ります。非 ASCII の内容（日本語、絵文字など）にはこちらを使用してください — スキャンコードベースの `keyboard.press` では直接入力できません。

**Raises**: 利用可能なクリップボードバックエンドが無い場合（例: `xclip` も `xsel` もインストールされていない Linux）は `pyperclip.PyperclipException`。`focus=True` の場合はフォーカスガードの例外。

______________________________________________________________________

## 型エイリアス

### `vrcpilot.types.Polygon`

```python
type Polygon = tuple[
    tuple[float, float],  # TL
    tuple[float, float],  # TR
    tuple[float, float],  # BR
    tuple[float, float],  # BL
]
```

`OCRWord.polygon` と `Detection.polygon` が使う 4 隅のポリゴン形です。座標は画像ローカルのピクセルです。

______________________________________________________________________

## エンドツーエンドのスニペット

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
