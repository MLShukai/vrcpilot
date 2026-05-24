# 使用ガイド

[English](usage.md) | **日本語**

このガイドでは `vrcpilot` で VRChat を操作する際の実践的なループ — 起動、観測、行動、検証 — を解説します。フラグ単位の詳細は [`cli.ja.md`](cli.ja.md)、同等の Python API については [`python-api.ja.md`](python-api.ja.md) を参照してください。

例は Linux + X11（または XWayland）を対象としています。Windows でも [Section 1](#1-load-environment-once-per-shell) の `.env` セットアップを省くだけで、同じ流れがそのまま動きます。

______________________________________________________________________

## 0. 前提条件チェックリスト

- **VRChat が Steam 経由でインストールされており**、Steam にログイン済みであること。
- **デスクトップセッションが X11 または XWayland であること。** `loginctl show-session "$XDG_SESSION_ID" -p Type` を実行し `Type=x11` であることを確認してください。Wayland ネイティブセッションはサポート対象外です — `focus()` / `unfocus()` は警告を出して `False` を返し、合成入力はウィンドウに届きません。
- **Steam が既に起動していること。** Steam が起動していない場合、`vrcpilot launch` は 30 秒の待機時間を Steam の起動画面で使い切り、最終的に `vrcpilot: VRChat did not start within 30.0s` で失敗します。先に Steam を起動しておいてください。
- **Linux 限定 — `vrcpilot` よりも先に `inputtino-python` をインストールすること。** Linux の入力バックエンドは [`inputtino`](https://github.com/games-on-whales/inputtino) を利用します。先にネイティブビルドの前提条件をインストールしたうえで、`vrcpilot` と同じ Python 環境に `inputtino-python` を導入してください。詳しくは [`README.ja.md` のインストール](../README.ja.md#%E3%82%A4%E3%83%B3%E3%82%B9%E3%83%88%E3%83%BC%E3%83%AB) を参照。
- **Linux 限定 — `/dev/uinput` への書き込み権限があること。** 合成入力は `/dev/uinput` を経由します。`sudo usermod -aG input "$USER"` を実行し、一度ログアウトして再ログインしてください。`groups` の出力に `input` が含まれていれば OK です。
- **画面がロックされていないこと。** スクリーンロック中はウィンドウ操作が不安定になります。

______________________________________________________________________

## 1. シェルごとに一度だけ環境を読み込む

SSH 経由のログインシェルでは通常 `DISPLAY` や `XAUTHORITY` が設定されていません。CLI セッションごとにプロジェクトルートの `.env` から読み込んでください:

```bash
set -a && . ./.env && set +a
```

最小限の `.env` は次のとおりです:

```
DISPLAY=:0
XAUTHORITY=/home/<you>/.Xauthority
```

`uv run` が出す `VIRTUAL_ENV=/usr does not match ... will be ignored` という警告は無害です — `uv run` は引き続きプロジェクトの `.venv` を使います。

Windows では `.env` は不要です。デスクトップセッションと SSH / RDP / ローカルターミナルが既定で同じディスプレイを共有します。

______________________________________________________________________

## 2. 起動とウォームアップ

```bash
vrcpilot launch --no-vr --screen-width 1280 --screen-height 720 --wait-timeout 60
```

- `--no-vr` はデスクトップモードを強制します。HMD のないマシンでは必ず指定してください。
- `--wait-timeout 60` は VRChat の PID が観測されるまでブロックし、観測できたら stdout に PID を出力します。終了コード `0` で起動成功を確認できます。
- 起動直後、VRChat は `01`〜`04` のアイコンが回転する **Launch Pad** 画面を表示します。これはメニューであってローディング表示ではなく、VRChat は裏でシェーダーコンパイル中であることがあります。
- 入力を送る前に **約 45 秒** 待ってください。それより早い入力はシェーダーコンパイルやアバターロードと競合する可能性があります。

______________________________________________________________________

## 3. 観測する — スクリーンショット / OCR / detect

VRChat は外から見ると不透明なので、すべての操作の前後で観測を行ってください。

### 3.1 スクリーンショット

```bash
vrcpilot screenshot -o /tmp/vrc.png > /tmp/vrc.yaml
```

stdout に出力される YAML には以下が記録されます:

- `path` — PNG の絶対パス（ファイルモード）、もしくは `image` — base64 PNG（インラインモード、`-o` を省略したとき）。
- `x`, `y` — VRChat ウィンドウの左上のデスクトップ絶対座標（情報用。下記の OCR / detect の結果はウィンドウローカル座標です）。
- `width`, `height` — 物理ピクセル単位のウィンドウサイズ。

### 3.2 OCR

`vrcpilot ocr` は自分では画面をキャプチャしません。`Screenshot` の YAML を pipe で渡すか、`--screenshot <path>` を指定してください:

```bash
# インラインパイプ（最短）
vrcpilot screenshot | vrcpilot ocr --viz /tmp/viz.png > /tmp/ocr.yaml

# 既存のスクリーンショット YAML を再利用
vrcpilot ocr --screenshot /tmp/vrc.yaml > /tmp/ocr.yaml
```

各 `words[i]` は次を持ちます:

- `text` と `confidence`。
- `pos.{polygon,bbox}` — ウィンドウローカルピクセル（原点は VRChat ウィンドウの左上）。

`vrcpilot mouse move` も `X Y` 引数を同じウィンドウローカル座標系で解釈するため、`pos.bbox` をそのまま流し込めます — 座標ごとの変換は不要です。詳しくは [`cli.ja.md` の座標系](cli.ja.md#coordinate-system) を参照してください。

`--viz [PATH]` を指定すると、スクリーンショット上に polygon を重ね描きした PNG を生成します。OCR の出力を目視で確認するのに使えます。

### 3.3 画像テンプレート検出

`vrcpilot detect` は `ocr` と同じ入力契約に従います。探したい UI 要素の小さな参照 PNG を用意してください:

```bash
vrcpilot screenshot | vrcpilot detect -q assets/launch-pad.png --threshold 0.85 --top-k 3 > /tmp/det.yaml
```

`detections[i]` は `confidence`、`scale`、`rotation`、そして `pos.{polygon,bbox}`（ウィンドウローカルピクセル）を持ちます。

`TM_CCOEFF_NORMED` は静的な UI 要素のピクセル単位で正確な切り抜きに対して最も良く機能します。テキストには OCR を使ってください。

______________________________________________________________________

## 4. 移動とクリック

```bash
# 600 / 360 を上で取得した OCR/detect の pos.bbox 中心に置き換えてください。
vrcpilot mouse move 600 360
vrcpilot mouse click left
```

- 座標は **VRChat ウィンドウローカルのピクセル** です — OCR / detect が `pos` の下に出すのと同じフレームです。`--rel` を付けると現在のカーソル位置からの差分に切り替わります。VRChat ウィンドウの外側の座標も拒否されず、そのまま OS に渡されます。
- `vrcpilot mouse click` の既定値は `left` および `--count 1` です。ダブルクリックには `--count 2` を、ボタンを短時間押し続けるには `--duration 0.05` を指定してください。

ドラッグのような down/up の組み合わせ操作は、単一の Python プロセス内で行ってください。合成入力デバイスは CLI プロセスが終了するとカーネルによって解放されるため、`mouse press` の後に別の `mouse release` を呼び出してもコマンド間でボタンを押し続けることはできません。

______________________________________________________________________

## 5. キーボード

```bash
vrcpilot keyboard press w --duration 1.0           # 約 1m 前進する
vrcpilot keyboard press shift w --duration 1.0     # 走って前進
vrcpilot keyboard press escape                     # 最前面のダイアログを閉じる
```

- `--duration 0.1` は VRChat が確実に受け取れる下限値です。これ以上小さくしないでください。
- 複数キーを並べると同時押し（down all → sleep → up reversed）になります。上の `shift w` は「shift を押したまま w をタップし、最後に両方離す」という意味です。
- 移動距離は `--duration` に比例します。ワールドごとに調整してください。
- CLI の各呼び出しは個別のプロセスです。あるキーを押したまま別の操作をしたい場合は、同じプロセス内から Python API の `vrcpilot.keyboard.down(...)` と `vrcpilot.keyboard.up(...)` を使ってください。

______________________________________________________________________

## 6. 非 ASCII テキスト

スキャンコードベースのキーボード入力では、日本語・絵文字・類似のテキストを直接タイプできません。`paste` を使うと OS のクリップボードに文字列をコピーしてから Ctrl+V を送信します:

```bash
vrcpilot paste "こんにちは、VRChat！"

# もしくは stdin から
cat msg.txt | vrcpilot paste
```

`paste` を実行する前に、まずテキストフィールドをクリックしてキーボードフォーカスを与えてください。`xclip` / `xsel` のない Linux 環境では `pyperclip.PyperclipException` が出ることがあります。いずれかをインストールしてください。

______________________________________________________________________

## 7. 視点操作

ワールド内（メニューが開いていない状態）では、デスクトップクライアントがマウスを取り込み、カーソルの動きでカメラを回せるようになります:

```bash
vrcpilot mouse move 200 0 --rel        # 右に約 200 px 分回転
vrcpilot mouse move 0 -100 --rel       # 上に約 100 px 分見上げる
```

メニューが開いているときは、カーソルは UI クリックモードに戻ります。

______________________________________________________________________

## 8. 映像と音声を録画する

`vrcpilot record` は映像、音声、またはその両方をキャプチャします。ファイル出力では、解決後のモードに応じてコンテナが選ばれます（映像を含む場合は MP4、音声のみは WAV）。stdout は常に自己記述形式の Matroska (MKV) バイトストリームになるため、`ffmpeg` などの下流ツールが追加のフォーマットフラグなしで取り込めます。

```bash
# 映像 + 音声 MP4、10 秒
vrcpilot record -o /tmp/vrc.mp4 --duration 10

# 映像のみ
vrcpilot record --video -o /tmp/vrc_video.mp4 --duration 10

# 音声のみ（VRChat のみ — Linux はネイティブ PipeWire、Windows は proc-tap、いずれもシステム音は含まない）
vrcpilot record --audio -o /tmp/vrc_audio.wav --duration 10

# 一時ファイルを使わずに ffmpeg に MKV をストリームして再エンコード
vrcpilot record --duration 5 | ffmpeg -i - -c copy /tmp/vrc.mkv
```

- `-o PATH` の拡張子はモードと一致させる必要があります（映像 / 両方は `.mp4`、音声のみは `.wav`）。不一致の場合は終了コード `2` で終わります。
- `--fps` の既定値は 30 で、`--audio` 単独と組み合わせると終了コード `2` で拒否されます。
- `--duration` を省略すると Ctrl+C まで録画し続けます。

フラグ全体のリファレンスと終了コードは [`cli.ja.md` の record](cli.ja.md#record) を参照してください。

______________________________________________________________________

## 9. VRChat のマイクへ音声を送る

`vrcpilot mic` は float32 PCM ストリームを仮想ケーブルの出力デバイスに再生します。VRChat 側でその仮想ケーブルをマイクとして設定しておけば、CLI が再生した音声は実際のマイクから話したかのように他のプレイヤーに届きます。主なユースケースは LLM エージェントの TTS を VRChat に繋ぐことです。

### 一度だけのセットアップ（Windows）

1. [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) をインストールし、プロンプトが出たら再起動します。
2. **設定 → システム → サウンド** を開き、再生デバイス `CABLE Input` と録音デバイス `CABLE Output` が両方表示されることを確認します。
3. VRChat の **Audio** 設定で、マイク入力を **`CABLE Output (VB-Audio Virtual Cable)`** に切り替えます。`vrcpilot mic` は `CABLE Input` に書き込み、VRChat はその音声を `CABLE Output` 経由で読み取ります。

### 一度だけのセットアップ（Linux）

1. PipeWire（`pipewire-pulse` 込み）と `libpulse0` がインストールされていることを確認します。
   Debian/Ubuntu の場合: `sudo apt-get install pipewire pipewire-pulse libpulse0`。
2. 仮想マイクを一度だけ登録します: `vrcpilot linux-mic register`。これにより
   `~/.config/pipewire/pipewire.conf.d/vrcpilot-mic.conf` が書き出され、
   `module-null-sink` がその場でロードされるので、現在のセッションでも
   すぐにデバイスが使えるようになります。
3. VRChat の **Audio** 設定で、マイク入力を
   **`Monitor of VRCPilot Virtual Mic`** に切り替えます。`vrcpilot mic` は
   `VRCPilotMic`（シンク）に書き込み、VRChat はその音声を
   `VRCPilotMic.monitor`（対応するモニターソース）から拾います。

ステータスは `vrcpilot linux-mic status` でいつでも確認でき、
`vrcpilot linux-mic unregister` で登録を解除できます。

### スモークテスト

```bash
vrcpilot mic -i greeting.wav
```

CLI は進捗（サンプルレート等）を stderr にログ出力し、WAV の再生が完了するまでブロックします。stdout は静かに保たれているので、生 PCM の生成元の下流に置いてもバイトストリームを汚しません:

```bash
# 任意の音声ソースを raw s16le にデコードして仮想マイクから再生する。
ffmpeg -i greeting.mp3 -f s16le -ar 48000 -ac 2 - \
  | vrcpilot mic --format s16le --rate 48000 --channels 2
```

### LLM エージェントからストリーミングする

`Mic` を一度だけ開き、エージェントが生成するチャンクを `play()` 呼び出しごとに 1 つずつ流し込んでください。`with` ブロックの間 `soundcard` プレイヤーが起動したままになるため、デバイス解決のコストはコンストラクタで一度だけ支払い、`play(chunk)` は反復ごとにバッファ書き込みだけを行います。

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

チャンクの shape は、コンストラクタで選んだチャンネル数と一致させる必要があります（モノラルは `(N,)`、マルチチャンネルは `(N, channels)`）。バックエンドの内部バッファが満杯のとき `play()` はブロックするため、ライブストリームに対して呼び出し側に自然なバックプレッシャーがかかります。

______________________________________________________________________

## 10. パイプラインパターン

### 観測 → 行動 → 再観測

```bash
# 操作前のスナップショット
vrcpilot screenshot -o /tmp/vrc_before.png

# 操作
vrcpilot keyboard press escape

# 操作後のスナップショット — 画像ビューワで開いて確認
vrcpilot screenshot -o /tmp/vrc_after.png
```

### OCR 駆動のクリック

スクリーンショットを `ocr` に流し、ある単語の最初の一致を選び、その中心をクリックします。例では [mikefarah/yq](https://github.com/mikefarah/yq) v4 を使っています。`jq` を使う場合は、フィルタを `'.words[] | select(.text == "Worlds") | .pos.bbox | @tsv'` に置き換えてください。

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

### ワンショットの後片付け

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

VRChat を起動し、Launch Pad をキャプチャして OCR にかけ、その後終了します — 環境のスモークテストとして便利です。

______________________________________________________________________

## 11. よくある失敗からの復旧

| 症状                                           | 想定される原因                                               | 対処                                                          |
| ---------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------- |
| `vrcpilot: VRChat did not start within 30.0s`  | Steam が起動していない、もしくは VRChat がインストール未済   | 先に Steam を起動し、Steam ライブラリでインストールを確認     |
| `vrcpilot focus` がサイレントに 1 で終了       | Wayland ネイティブセッション、または VRChat ウィンドウ未生成 | X11 / XWayland に切り替え、ウォームアップを待つ               |
| 入力コマンドから `VRChatNotFocusedError`       | 呼び出し直前にウィンドウのフォーカスが外れた                 | `vrcpilot focus` で再フォーカスしてから再試行                 |
| Tab キーが効かない                             | 2026 系の UI では Tab がメニューに割り当てられなくなった     | Escape（Launch Pad）と R（Radial Action Menu）を使う          |
| `keyboard press` が無視される                  | `--duration` を `0.1` 未満に下げている                       | 既定の `0.1` 以上に戻す                                       |
| `mouse move` が OCR ターゲットから大きく外れる | OCR/detect の `pos` をデスクトップ絶対座標として扱っている   | `pos.bbox` をそのまま渡す — `mouse move` はウィンドウローカル |
| Linux で `pyperclip.PyperclipException`        | クリップボードバックエンドが未インストール                   | `sudo apt-get install xclip`（もしくは `xsel`）               |
| キャプチャがハング、または即座に失敗           | Wayland ネイティブセッション、または画面ロック中             | X11 / XWayland に切り替え、画面のロックを解除                 |

______________________________________________________________________

## 12. Python での同等処理

ここまでの内容はすべて [`python-api.ja.md`](python-api.ja.md) に Python 版があります。エンドツーエンドの流れは次のとおりです:

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

複数の操作にまたがってキーやボタンを押し続けたい場合は、ひとつの Python プロセス内で `keyboard.down` / `up` と `mouse.press` / `release` を使ってください。これらのハーフアクション API は意図的に CLI から省かれています。CLI の各呼び出しは個別のプロセスになるためです。
