# CLI リファレンス

[English](cli.md) | **日本語**

`vrcpilot` コマンドのフラグごとのリファレンスです。タスク指向のウォークスルーは [`usage.ja.md`](usage.ja.md)、同等の Python API は [`python-api.ja.md`](python-api.ja.md) を参照してください。

`vrcpilot --help` および `vrcpilot <subcommand> --help` は実行時に同じ内容を表示します。

## 規約

- サブコマンドは成功時に終了コード `0`、回復可能な失敗時に `1` を返し、stderr へ `vrcpilot: <message>` の 1 行を出力します。一部のコマンドは入力形状エラーに対して `2` も使用します（例えば `record` は `-o` の拡張子の不一致や `--fps` と `--audio` の組み合わせを終了コード `2` で拒否します）。該当ケースは以下で個別に明記します。
- `vrcpilot --version` は解決済みのパッケージバージョンを表示します（`importlib.metadata` 経由で読み込むため `pyproject.toml` と常に同期します）。
- CLI は `argcomplete` 対応です（`PYTHON_ARGCOMPLETE_OK` が [`src/vrcpilot/cli/__init__.py`](../src/vrcpilot/cli/__init__.py) で宣言されています）。セットアップは [`README.ja.md`](../README.ja.md#%E3%82%B7%E3%82%A7%E3%83%AB%E8%A3%9C%E5%AE%8C) を参照してください。

### `Screenshot` YAML の受け渡し

`ocr` および `detect` は自前で画面をキャプチャしません。`vrcpilot screenshot` が生成する `Screenshot` YAML を入力として受け取ります。[`cli/_common.py::resolve_screenshot`](../src/vrcpilot/cli/_common.py) はその入力を以下の順序で解決します:

1. `-s` / `--screenshot <path>` が指定されていればそれを使用します。ファイルが常に優先され、この分岐では stdin は読み込みすらされません。
2. stdin が TTY **でない** 場合は stdin から読みます（つまり `vrcpilot screenshot ...` からのパイプ）。
3. それ以外の場合は usage メッセージを stderr に出力して `1` で終了します。

両形式は同等に扱われます。最新キャプチャをパイプ経由で渡すことも、保存済みの YAML ファイルを渡すこともできます。

### 座標系

OCR と detect はマッチごとに 1 つの座標空間を出力します:

- `pos.{polygon,bbox}` — ウィンドウローカルピクセル。VRChat ウィンドウの左上が原点です。

`vrcpilot mouse move X Y` は `(X, Y)` を **同じウィンドウローカル座標系** で解釈するため、OCR / detect の出力と `mouse move` は変換なしでラウンドトリップします。デスクトップ絶対座標のビューは別途用意されていません — 以前あった `display_pos.{polygon,bbox}` フィールドは削除されました。

ウィンドウ自体のデスクトップ絶対位置が必要な場合、`screenshot` YAML が依然としてウィンドウの左上を `x` / `y`（モニタインデックスを `monitor_index`）に記録しています。

______________________________________________________________________

## launch

Steam を介して VRChat を起動します。

```
vrcpilot launch [--app-id INT] [--steam-path PATH] [--no-vr]
                [--screen-width N] [--screen-height N]
                [--osc-in-port N] [--osc-out-ip STR] [--osc-out-port N]
                [--wait-timeout SECONDS]
```

| Option                   | Default     | 説明                                                                                                   |
| ------------------------ | ----------- | ------------------------------------------------------------------------------------------------------ |
| `--app-id INT`           | `438100`    | Steam App ID。VRChat 形状の非 VRChat アプリをテストするとき以外は変更しないでください。                |
| `--steam-path PATH`      | auto-detect | `steam.exe` / `steam` バイナリへの明示的なパス。                                                       |
| `--no-vr`                | off         | デスクトップモードを強制します（VRChat に `--no-vr` を渡します）。HMD のないマシンで使用してください。 |
| `--screen-width N`       | unset       | Unity に `-screen-width N` を渡します。                                                                |
| `--screen-height N`      | unset       | Unity に `-screen-height N` を渡します。                                                               |
| `--osc-in-port N`        | unset       | OSC を有効化し、受信 UDP ポートを設定します。これが指定された場合のみ OSC 設定が転送されます。         |
| `--osc-out-ip STR`       | `127.0.0.1` | OSC 送信 IP（`--osc-in-port` 指定時のみ意味を持ちます）。                                              |
| `--osc-out-port N`       | `9001`      | OSC 送信ポート（`--osc-in-port` 指定時のみ意味を持ちます）。                                           |
| `--wait-timeout SECONDS` | `30`        | VRChat の PID が現れるのを待つ秒数。`0` を指定すると待たずに即座に返ります。                           |

**出力**: `--wait-timeout > 0` で PID が観測された場合、その PID が stdout に 1 行で出力されます。Steam が見つからない場合や待機タイムアウトの場合は、`vrcpilot: <message>` が stderr に書き出されます。

**終了コード**: 成功時 `0`、待機タイムアウト時 `1`、Steam が見つからない場合 `2`。

**副作用**: Steam がまだ起動していなければ起動し、その後に指定されたアプリを起動します。

______________________________________________________________________

## pid

現在実行中の VRChat プロセス ID を一覧表示します。

```
vrcpilot pid
```

**出力**: stdout に 1 行 1 PID で出力します。何も実行されていない場合は無出力です。

**終了コード**: PID が 1 つ以上見つかれば `0`、VRChat プロセスが 1 つも実行されていなければ `1`。

**副作用**: なし。

______________________________________________________________________

## terminate

実行中の VRChat プロセスをすべて終了させます。冪等です — 何も実行されていない状態で呼んでも安全です。

```
vrcpilot terminate
```

**出力**: 終了させた PID を stdout に 1 行ずつ出力します。実行中のプロセスがなければ空です。

**終了コード**: 常に `0`。

**副作用**: マッチした各プロセスへ強制終了シグナルを送ります。

______________________________________________________________________

## focus

VRChat ウィンドウを最前面に持ってきます。

```
vrcpilot focus
```

**出力**: 成功時はサイレント。失敗時は `vrcpilot: could not focus VRChat` が stderr に書き出されます。

**終了コード**: 成功時 `0`、失敗時 `1`（VRChat 未起動、ウィンドウ未マップ、X11 / Wayland-native 非対応など）。

**副作用**: デスクトップのフォーカスウィンドウを変更します。

______________________________________________________________________

## unfocus

VRChat ウィンドウを z オーダーの最背面へ送ります（他の特定のウィンドウを前面に出すわけではありません）。

```
vrcpilot unfocus
```

**出力**: 成功時はサイレント。失敗時は `vrcpilot: could not unfocus VRChat` が stderr に書き出されます。

**終了コード**: 成功時 `0`、失敗時 `1`。

**副作用**: デスクトップのウィンドウスタックを並べ替えます。

______________________________________________________________________

## screenshot

ワンショットキャプチャを取得し、`Screenshot` YAML を出力します。

```
vrcpilot screenshot [-o PATH]
```

| Option                     | Default | 説明                                                                                                                                            |
| -------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `-o PATH`, `--output PATH` | unset   | PNG を `PATH` に書き出します。YAML は絶対パスを `path:` に記録します。省略時は PNG を YAML の `image:` に base64 で埋め込みます（パイプ向け）。 |

**出力**: 以下のトップレベルキーを持つ YAML ドキュメントを stdout に出力します（順序は保持され、アルファベット順ではありません）:

- `path`（ファイルモード）または `image`（インラインモード）
- `x`, `y`, `width`, `height`
- `monitor_index`
- `captured_at`（ISO-8601 UTC）

**終了コード**: 成功時 `0`、キャプチャ失敗時 `1`。

**副作用**: `-o` 指定時のみ PNG をディスクに書き出します。`-o PATH` の親ディレクトリは事前に存在している必要があります。親ディレクトリが存在しない場合、現状はクリーンな exit-1 ではなく `FileNotFoundError` のトレースバックとして現れます。

______________________________________________________________________

## record

VRChat の映像 / 音声をファイルへ録画するか、stdout にストリーム配信します。映像は VRChat ウィンドウです（フォーカス不要、[`Capture`](python-api.ja.md#vrcpilotcapturecapture) と同じバックエンドを使用）。音声は VRChat 単体のもので、Linux ではネイティブ PipeWire パイプライン、Windows では `proc-tap` プロセスループバックを使用するため、他アプリケーションのシステム音声は混入しません。

```
vrcpilot record [-o PATH] [--video] [--audio] [--fps FLOAT] [--duration SECONDS]
```

| Option                     | Default      | 説明                                                                                                                                                                                                                                                                                                                                            |
| -------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-o PATH`, `--output PATH` | stdout (MKV) | ファイル出力先。既存ディレクトリを指定した場合、ファイル名はモードに応じて `<dir>/vrcpilot_record_<YYYYMMDD_HHMMSS>.{mp4,wav}` になります。ファイルパスを指定した場合はそのまま使われ、拡張子はモードに一致している必要があります（映像 / 両方は `.mp4`、音声のみは `.wav`）。未指定の場合、自己記述形式の MKV ストリームが stdout に流れます。 |
| `--video`                  | off          | 映像を録画します。`--audio` と組み合わせる、またはどちらのフラグも指定しない場合は映像と音声の両方を録画します。                                                                                                                                                                                                                                |
| `--audio`                  | off          | 音声を録音します。`--video` と組み合わせる、またはどちらのフラグも指定しない場合は映像と音声の両方を録画します。                                                                                                                                                                                                                                |
| `--fps FLOAT`              | `30.0`       | 目標とする映像フレームレート。音声のみモードとの併用はできません。                                                                                                                                                                                                                                                                              |
| `--duration SECONDS`       | unbounded    | この秒数経過後に停止します。指定しない場合は中断 (Ctrl+C) されるまで録画を続けます。                                                                                                                                                                                                                                                            |

### モード解決

`--video` / `--audio` フラグは以下 3 つの内部モードのいずれかに対応付けられます:

| `--video` | `--audio` | resulting mode | required file extension |
| --------- | --------- | -------------- | ----------------------- |
| absent    | absent    | `both`         | `.mp4`                  |
| present   | absent    | `video`        | `.mp4`                  |
| absent    | present   | `audio`        | `.wav`                  |
| present   | present   | `both`         | `.mp4`                  |

解決されたモードと拡張子が一致しない `-o PATH` を渡すと、`vrcpilot: --video requires .mp4 output (got: ...)`、`vrcpilot: --audio requires .wav output (got: ...)`、または `vrcpilot: video+audio output requires .mp4 (got: ...)` のいずれかとともに `2` で終了します。

`--fps` を `--audio` 単独と組み合わせると、`vrcpilot: --fps is not meaningful with --audio (drop --fps or remove --audio)` とともに `2` で終了します。

### 出力

- **ファイルモード**（`-o PATH` がファイルまたはディレクトリ）: 進捗メッセージは stderr に出力され、完了時に保存ファイルの絶対パスが stdout に 1 度だけ出力されます。ファイルは MP4 コンテナ内の H.264（libx264 / yuv420p）+ AAC、または WAV コンテナ内の `pcm_s16le` 48 kHz ステレオのいずれかです。
- **stdout パイプモード**（`-o` 省略時）: モードを問わず自己記述形式の Matroska (MKV) バイトストリームが stdout に書き出されます（`matroska` コンテナ、H.264 映像および / または AAC 音声）。下流のツールはこれを直接消費できます（例: `vrcpilot record --duration 5 | ffmpeg -i - -c copy /tmp/out.mkv`）。進捗メッセージは stderr に出力されるため、stdout のバイトストリームはパイプ向けに汚れないままです。stdout が TTY の場合パイプモードは実行を拒否します（終了コード `1`）。

### 終了コード

- `0` — 成功。
- `1` — 実行時エラー: VRChat が起動していない、フレームや音声サンプルがキャプチャできなかった、またはパイプモードで stdout が TTY。
- `2` — 入力形状エラー: `-o` の拡張子が解決されたモードと一致しない、または音声のみモードに `--fps` が指定された。

### 副作用

- ファイルモードでは MP4 または WAV をディスクに書き出します。親ディレクトリは事前に存在している必要があります。
- 録画の音声部分について、ホストプラットフォーム用の Speaker バックエンド（Linux では PipeWire パイプライン、Windows では `proc-tap` プロセスループバックセッション）を VRChat の PID に対して取得します。

______________________________________________________________________

## mic

仮想マイクデバイスに PCM 音声を流し込み、VRChat にマイク入力として拾わせます。WAV ファイル (`-i path.wav`) または stdin の raw `s16le` から読み込むため、`ffmpeg -f s16le ...` などの上流ツールや Python 製の LLM-TTS パイプラインから音声を直接 VRChat にパイプできます。主な用途は LLM エージェントの TTS を VRChat に流すことです。

```
vrcpilot mic [-i PATH] [--device NAME] [--rate HZ] [--channels {1,2}]
             [--format {auto,wav,s16le}] [--chunk-ms MS]
```

| Option                      | Default | 説明                                                                                                                                                                                                                                             |
| --------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `-i PATH`, `--input PATH`   | `-`     | 音声ソース。`-` は stdin から読み込みます。`.wav` パスは標準ライブラリの `wave` モジュールでデコードします（16-bit 符号付き PCM 必須）。それ以外のパスには `--format s16le` が必要です。                                                         |
| `--device NAME`             | unset   | 出力デバイス名の部分文字列（`soundcard` のマッチングに渡されます）。未指定時は `$VRCPILOT_MIC_DEVICE`、続いて OS のデフォルト（Windows では `CABLE Input`、Linux では `vrcpilot linux-mic register` 後の `VRCPilotMic`）にフォールバックします。 |
| `--rate HZ`                 | `48000` | raw `s16le` 入力のサンプルレート。WAV では無視されます（WAV ヘッダが優先）。                                                                                                                                                                     |
| `--channels {1,2}`          | `2`     | raw `s16le` 入力のチャネル数。デフォルトは `2`（ステレオ）。WAV では無視されます（WAV ヘッダが優先）。                                                                                                                                           |
| `--format {auto,wav,s16le}` | `auto`  | 入力の解釈を強制します。`auto` + ファイル → 拡張子が `.wav` の場合のみ WAV としてデコードします（他の拡張子は `2` で終了）。`auto` + stdin → raw `s16le`。                                                                                       |
| `--chunk-ms MS`             | `100`   | raw `s16le` ストリーミングのチャンクサイズ（ミリ秒）。プル間隔のみに影響し、バックエンドはチャンク境界を越えて排出します。                                                                                                                       |

**入力解決**:

- `-i -`（デフォルト） — stdin から読み込みます。stdin が TTY の場合は再生するデータがないため実行を拒否します（終了コード `2`）。
- `-i path.wav`（または `--format wav` を伴う任意のパス） — 16-bit 符号付き PCM WAV ファイルとして開きます。
- `-i path.raw --format s16le` — `--rate` / `--channels` に従って raw リトルエンディアン符号付き 16-bit PCM として開きます。

**出力**: 進捗メッセージは stderr に書き出されます（サンプルレートなど）。stdout は **サイレント** なので、このサブコマンドはプロデューサーパイプの下流に置いてもバイトストリームを汚しません。

**終了コード**: 成功時 `0`。デバイス検索失敗 (`MicDeviceNotFoundError`)、未対応の WAV（16-bit 符号付き PCM 以外）、`soundcard` / libpulse / WASAPI のランタイム失敗、ファイルオープンエラー、`soundcard` 未インストールの場合は `1`。引数形状エラー（TTY に対する `-i -` や、非 WAV ファイルパスに対する `--format auto`）は `2`。

**副作用**: 解決されたデバイスで `soundcard` の出力プレイヤーを開き、float に変換したペイロードを書き込みます。Windows + VB-Cable では、これにより（マイクとして `CABLE Output` を使用するよう設定された）VRChat が実マイク入力と同じように音声を受け取ります。Linux + PipeWire では音声は `Monitor of VRCPilot Virtual Mic` を経由して VRChat に届きます。

**前提**: Windows では [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) をインストールし、VRChat のマイクを `CABLE Output` に切り替えてください。Linux では先に `vrcpilot linux-mic register` を実行（これで `VRCPilotMic` PipeWire シンクが作成されます）し、VRChat のマイクを `Monitor of VRCPilot Virtual Mic` に切り替えてください。また `soundcard` が CFFI 経由でリンクしている関係で `libpulse0` のインストールも必要です。

**使用例**:

```bash
# Play a WAV file
vrcpilot mic -i greeting.wav

# Decode any audio source to raw s16le and pipe it through the virtual mic
ffmpeg -i greeting.mp3 -f s16le -ar 48000 -ac 2 - \
  | vrcpilot mic --format s16le --rate 48000 --channels 2

# Raw PCM file with an explicit format
vrcpilot mic -i tts.raw --format s16le --rate 24000 --channels 1
```

______________________________________________________________________

## linux-mic

Linux 上の永続的な `VRCPilotMic` 仮想マイク（PipeWire `module-null-sink`）を管理します。同じ親サブパーサ配下に 3 つのアクションが公開されています:

```
vrcpilot linux-mic register   [--no-runtime-load] [--suffix NAME]
vrcpilot linux-mic unregister [--suffix NAME | --all]
vrcpilot linux-mic status     [--suffix NAME | --all]
```

| Action       | 説明                                                                                                                                                |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `register`   | 永続化用の PipeWire 設定フラグメントを書き出し、（デフォルトで）`module-null-sink` を即座にロードして現在のセッションでシンクを使えるようにします。 |
| `unregister` | 設定フラグメントを削除し、マッチするランタイムモジュールがあればアンロードします。冪等です — 登録されていない状態でも `0` で終了します。            |
| `status`     | 設定が存在するか、ランタイムモジュールがロードされているか、`soundcard` がデバイスを認識できるかを報告します。Linux 上では常に `0` で終了します。   |

| Option              | Applies to              | Default | 説明                                                                                                                                                                                                            |
| ------------------- | ----------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--no-runtime-load` | `register`              | off     | 即時の `pulsectl` `module_load` ステップをスキップします。永続設定は書き出されるので、PipeWire を再起動すれば後のセッションで反映されます。                                                                     |
| `--suffix NAME`     | all actions             | unset   | `register` では名前付きの追加 sink (`VRCPilotMic_<NAME>`) を作成します。`unregister` / `status` では指定 suffix のみを対象とします。デフォルト（未指定）は空 suffix の `VRCPilotMic` です。`--all` と排他です。 |
| `--all`             | `unregister` / `status` | off     | `unregister` では登録済みの全 suffix を一括解除します。`status` では登録済みの全 suffix を列挙します。`--suffix` と排他です。                                                                                   |

**出力**: 人間向けの進捗は stderr に出力されます（設定パス、ランタイムロード結果、VRChat 側のヒント）。`status` アクションはこれに加え、固定語彙の機械可読サマリを stdout に書き出します: `config: {present|absent}`、`config_path: <path>`、`runtime: {loaded|not loaded|unavailable}`、`soundcard: {visible|not visible|unavailable}`（1 行 1 キー）。`unavailable` は、原因となるプローブ失敗を説明する `error: <message>` 行が stderr に併記されます。

`status` の出力フォーマットは指定オプションで変わります:

- 引数なし（空 suffix デフォルト） — 従来通り上記 4 行を出力します。
- `--suffix NAME` — 先頭に `suffix: <name>` 行が追加され、合計 5 行になります。
- `--all` — 登録済みの各 suffix エントリ（先頭に `suffix:` 行 + 既存 4 行の計 5 行）を **空行 1 行** で区切って列挙します。登録が 0 件の場合は stdout に `suffix: (none)` / `config: absent` / `config_path: <dir>/` を出力し、stderr に案内メッセージを書いて exit `0` で終了します。

**終了コード**:

- `0` 成功時（`register` / `unregister` でランタイムステップが警告に降格した場合、および `status` の Linux プローブ結果すべてを含む）。
- `2` 非 Linux プラットフォーム — Windows 向けに VB-Cable を案内するヒントとともにショートサーキットします。

**副作用**: `$XDG_CONFIG_HOME/pipewire/pipewire.conf.d/vrcpilot-mic.conf`（変数未設定時は `~/.config/...`）を書き出し / 削除します。`--suffix NAME` を指定した場合は同ディレクトリ配下に `vrcpilot-mic-<NAME>.conf` という独立したファイルが書き込まれます（空 suffix の `vrcpilot-mic.conf` とは別ファイルとして共存します）。ランタイムロードが有効な場合は `pulsectl.Pulse.module_load("module-null-sink", ...)` を呼び出します — ランタイム失敗（`pulsectl` 未インストール、コントロールプレーンエラー）は、永続設定が真実の源であるため、終了コードを変更せず stderr の警告に降格します。

______________________________________________________________________

## speaker

VRChat の出力音声を PID 単位で任意の出力デバイスへリレーします。多重起動した VRChat の音声を物理 / 仮想スピーカーへ振り分ける用途で、OS のアプリ別出力ポリシー (Windows `IAudioPolicyConfig` 等) に依存しないユーザー空間リレーです。背景・ユースケース・仮想 cable のセットアップは [`virtual-audio.md`](virtual-audio.md) を参照してください。

`vrcpilot speaker list` / `vrcpilot speaker route` の 2 アクションを公開しています。

### `speaker list`

```
vrcpilot speaker list
```

出力デバイスを YAML で列挙します。

**出力**: 以下の形の YAML ドキュメントを stdout に出力します。並びは「OS デフォルトが先頭、続いて `name` 昇順 (Python のコードポイント比較)」です。デバイスが 1 つもない環境では `devices: []` を出力します。

```yaml
devices:
  - id: "<backend-specific id>"
    name: "<human-readable name>"
    is_default: true
  - id: "..."
    name: "..."
    is_default: false
```

**終了コード**: 成功時 `0`、デバイス列挙自体に失敗した場合（`soundcard` 未インストール、libpulse / WASAPI のロード失敗、ルーティングエラー）`1`。

**副作用**: なし。

### `speaker route`

```
vrcpilot speaker route --pid PID [--device QUERY]
                       [--chunk-seconds SECONDS] [--blocksize FRAMES]
```

指定 PID の VRChat 音声を選んだ出力デバイスへ転送します。foreground 実行で、Ctrl+C で停止します。

| Option                    | Default       | 説明                                                                                                                                                                                                                                                                             |
| ------------------------- | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--pid PID`               | required      | リレー対象の VRChat PID。多重起動分離が本コマンドの存在理由のため、他の PID 依存サブコマンドと違い自動 resolve は行わず **必須** です。                                                                                                                                          |
| `--device QUERY`          | OS デフォルト | 出力デバイスの解決クエリ。`id` 完全一致 → `name` 完全一致（大文字小文字を区別）→ `name` 部分一致（小文字化して `in` 判定）の順で 1 つに解決します。いずれかのステージで複数ヒットすると即エラー終了します。省略時は OS の既定スピーカーを使用します。                            |
| `--chunk-seconds SECONDS` | `0.02`        | キャプチャ側 (`SpeakerLoop`) のチャンク秒数。小さいほど低レイテンシ、大きいほど underrun に強くなります。レイテンシ調整は [`virtual-audio.md`](virtual-audio.md#%E3%83%AC%E3%82%A4%E3%83%86%E3%83%B3%E3%82%B7%E8%AA%BF%E6%95%B4%E3%82%AC%E3%82%A4%E3%83%89) を参照してください。 |
| `--blocksize FRAMES`      | `None`        | `soundcard` プレイヤーのブロックサイズ（フレーム数）。`None` は `soundcard` バックエンド既定値を使います。                                                                                                                                                                       |

**出力**: 起動直後に stderr へ解決後デバイスを 1 行で報告します: `route: pid=<PID> device='<NAME>'`。`--device` を省略した場合は末尾に ` (system default)` が付きます。stdout は **サイレント** です（パイプ汚染なし）。

**終了コード**: 正常終了（Ctrl+C）時 `0`。指定 PID の VRChat が起動していない、`--device` クエリにマッチするデバイスがない (`DeviceNotFoundError`)、`--device` が複数デバイスに曖昧マッチ (`AudioRoutingError`)、`soundcard` / libpulse / WASAPI のランタイム失敗、`soundcard` 未インストール、Windows / Linux 以外のホストで実行した場合は `1`。`--pid` 未指定など argparse の引数形状エラーは `2`。

**副作用**: 指定 PID 向けに platform 別 Speaker バックエンド（Linux: PipeWire パイプライン、Windows: `proc-tap` プロセスループバックセッション）を取得し、`soundcard` 出力プレイヤーを開いてキャプチャしたフレームを転送します。Ctrl+C 受信時はキャプチャ → プレイヤーの順で確実に解放されます。VRChat プロセスが route 実行中に終了した場合、内部のキャプチャワーカーが例外を捕捉しますが、CLI 側は `time.sleep` ループに留まるため自動停止はせず、ユーザーが Ctrl+C で能動的に停止する必要があります（例外は停止時に surface します）。

______________________________________________________________________

## mouse

VRChat に合成マウス入力を送ります。すべてのアクションは VRChat が起動中かつフォーカスされていることをガードします。

### `mouse move`

```
vrcpilot mouse move X Y [--rel]
```

| Argument | 説明                                                                                                                                                                |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `X`, `Y` | **VRChat のウィンドウローカルピクセル** で表したターゲット位置 — `ocr` / `detect` の `pos.bbox` と同じ座標系です。[座標系](#coordinate-system) を参照してください。 |
| `--rel`  | `X`, `Y` を現在のカーソル位置からの相対デルタとして扱います。VRChat ウィンドウ外の座標は拒否されず、そのまま OS に渡されます。                                      |

### `mouse click`

```
vrcpilot mouse click [BUTTON ...] [--count N] [--duration SECONDS]
```

| Argument / Option    | Default | 説明                                                                                                                            |
| -------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `BUTTON ...`         | `left`  | `left`, `right`, `middle` のいずれかを 1 つ以上指定します。複数指定すると同時に押されます。                                     |
| `--count N`          | `1`     | クリックを `N` 回繰り返します。                                                                                                 |
| `--duration SECONDS` | `0.0`   | 1 クリックあたりボタンを押し続ける時間。`0.0`（デフォルト）はスリープをスキップし、press / release のペアが連続して発生します。 |

### `mouse scroll`

```
vrcpilot mouse scroll AMOUNT
```

| Argument | 説明                                                                             |
| -------- | -------------------------------------------------------------------------------- |
| `AMOUNT` | 垂直方向のスクロール単位。正の値で下にスクロール、負の値で上にスクロールします。 |

**終了コード**（`mouse` サブコマンド共通）: 成功時 `0`、VRChat が起動していないかフォーカスされていない場合 `1`。

**副作用**: [`pydirectinput`](https://github.com/learncodebygaming/pydirectinput)（Windows）または [`inputtino`](https://github.com/games-on-whales/inputtino)（Linux uinput）経由で入力を合成します。

> `mouse press` / `mouse release` は意図的に公開していません。CLI プロセスが終了するとカーネルがボタンを離すため、別々の呼び出しを跨いで down / up をペアにできません。down / up を対で動かしたい場合は、単一の Python プロセスから [`vrcpilot.mouse.press` / `vrcpilot.mouse.release`](python-api.ja.md#vrcpilotmouse) を呼んでください。

______________________________________________________________________

## keyboard

VRChat に合成キータップ（またはコード）を送ります。

```
vrcpilot keyboard press KEY [KEY ...] [--duration SECONDS]
```

| Argument / Option    | Default  | 説明                                                                                                               |
| -------------------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| `KEY ...`            | required | キー名を 1 つ以上指定します。複数指定するとコードになります（全部 down → sleep → 逆順に up）。                     |
| `--duration SECONDS` | `0.1`    | コード全体の保持時間。`0.1` より小さい値は設定しないでください — VRChat / Unity は短すぎるタップを取りこぼします。 |

有効な `KEY` の値: `a`–`z`, `0`–`9`, `f1`–`f12`、修飾キー (`shift` / `shiftleft` / `shiftright`, `ctrl` / `ctrlleft` / `ctrlright`, `alt` / `altleft` / `altright`, `win` / `winleft` / `winright`)、ナビゲーション (`up`, `down`, `left`, `right`, `home`, `end`, `pageup`, `pagedown`)、編集 (`backspace`, `delete`, `insert`, `tab`, `enter`, `escape`, `space`)、記号 (`minus`, `equals`, `lbracket`, `rbracket`, `backslash`, `semicolon`, `quote`, `comma`, `period`, `slash`, `backtick`)。

**終了コード**: 成功時 `0`、VRChat が起動していないかフォーカスされていない場合 `1`。

**副作用**: 上記と同様に入力を合成します。

> `keyboard down` / `keyboard up` は `mouse press` / `mouse release` と同じ理由で意図的に公開していません。

______________________________________________________________________

## paste

クリップボード + Ctrl+V 経由で任意の Unicode テキストを入力します。スキャンコードベースの `keyboard press` では直接タイプできない非 ASCII コンテンツ（日本語、絵文字など）はこちらを使用してください。

```
vrcpilot paste [TEXT]
```

| Argument            | 説明                                                                                                                                                        |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TEXT` (positional) | 貼り付けるテキスト。省略可。省略時に stdin がパイプされていれば stdin から読み込みます。省略時に stdin が TTY なら、入力でブロックせずに `2` で終了します。 |

**終了コード**: 成功時 `0`、VRChat フォーカスガードの失敗やクリップボードバックエンドエラー時 `1`、`TEXT` を省略し stdin が TTY の場合 `2`。

**副作用**: OS のクリップボードに書き込み、その後 Ctrl+V を送信します。

______________________________________________________________________

## ocr

`Screenshot` YAML に対して OCR を実行します。

```
vrcpilot ocr [-s YAML | --screenshot YAML] [--viz [PATH]]
```

| Option                         | Default | 説明                                                                                                                                                                                                                        |
| ------------------------------ | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-s YAML`, `--screenshot YAML` | unset   | `Screenshot` YAML を `YAML` から読み込みます。指定時はパイプされていても stdin は無視されます — ファイルが常に優先されます。                                                                                                |
| `--viz [PATH]`                 | off     | 引数なしで指定した場合、可視化 PNG を `./vrcpilot_ocr_viz_<UTC>.png` に書き出します。ディレクトリを指定した場合はそのディレクトリ内に同じファイル名で書き出します。ファイルパスを指定した場合はそのままのパスを使用します。 |

**入力**: stdin パイプ（stdin が TTY でない場合）または `--screenshot PATH`。[Screenshot YAML の受け渡し](#screenshot-yaml-hand-off) を参照してください。

**出力**: 以下を含む YAML ドキュメントを stdout に出力します:

- `captured_at`（ISO-8601 UTC）
- `window` — `x`, `y`, `width`, `height`, `monitor_index`
- `words[]` — 各要素は `text`, `confidence`, `pos.{polygon,bbox}`（ウィンドウローカルピクセル）を持ちます
- `viz_path` — `--viz` を使用した場合のみ存在します

**終了コード**: 成功時 `0`、スクリーンショット入力を解決できない場合や OCR が失敗した場合 `1`。

**副作用**: オプションで可視化 PNG をディスクに書き出します。

______________________________________________________________________

## detect

`Screenshot` YAML に対して画像テンプレート検出を実行します。

```
vrcpilot detect -q QUERY_PATH [-s YAML | --screenshot YAML]
                [--threshold FLOAT] [--top-k INT] [--viz [PATH]]
```

| Argument / Option              | Default                 | 説明                                                                                            |
| ------------------------------ | ----------------------- | ----------------------------------------------------------------------------------------------- |
| `-q PATH`, `--query PATH`      | required                | クエリ画像（PNG / JPG）。                                                                       |
| `-s YAML`, `--screenshot YAML` | unset                   | `Screenshot` YAML を `YAML` から読み込みます。指定時はパイプされていても stdin は無視されます。 |
| `--threshold FLOAT`            | engine default (`0.85`) | `cv2.matchTemplate`（`TM_CCOEFF_NORMED`）の閾値。範囲は `-1.0`–`1.0`。                          |
| `--top-k INT`                  | unbounded               | 信頼度上位 `K` 件のみを残します。                                                               |
| `--viz [PATH]`                 | off                     | `ocr --viz` と同じ意味ですが、デフォルトファイル名は `vrcpilot_detect_viz_<UTC>.png` です。     |

**入力**: `ocr` と同じ受け渡しルールです。

**出力**: 以下を含む YAML ドキュメントを stdout に出力します:

- `captured_at`（ISO-8601 UTC）
- `window` — `x`, `y`, `width`, `height`, `monitor_index`
- `query` — `path`, `width`, `height`
- `detections[]` — 各要素は `confidence`, `scale`, `rotation`, `pos.{polygon,bbox}`（ウィンドウローカルピクセル）を持ちます
- `viz_path` — `--viz` を使用した場合のみ存在します

**終了コード**: 成功時 `0`、スクリーンショット入力を解決できない場合、クエリ画像をロードできない場合、または検出に失敗した場合 `1`。

**副作用**: オプションで可視化 PNG をディスクに書き出します。
