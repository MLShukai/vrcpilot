# vrcpilot

[English](README.md) | **日本語**

[![PyPI](https://img.shields.io/pypi/v/vrcpilot?color=blue)](https://pypi.org/project/vrcpilot/)
[![Python](https://img.shields.io/pypi/pyversions/vrcpilot)](https://pypi.org/project/vrcpilot/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Test](https://github.com/MLShukai/vrcpilot/actions/workflows/test.yml/badge.svg)](https://github.com/MLShukai/vrcpilot/actions/workflows/test.yml)
[![Type Check](https://github.com/MLShukai/vrcpilot/actions/workflows/type-check.yaml/badge.svg)](https://github.com/MLShukai/vrcpilot/actions/workflows/type-check.yaml)
[![Format & Lint](https://github.com/MLShukai/vrcpilot/actions/workflows/pre-commit.yml/badge.svg)](https://github.com/MLShukai/vrcpilot/actions/workflows/pre-commit.yml)

Windows / Linux 上の VRChat デスクトップクライアントを Python から自動操作するためのツールキットです。起動、フォーカス、画面キャプチャ、OCR、画像テンプレート検出、合成入力を、型付きの Python API と `vrcpilot` CLI から扱えます。

> **破壊的変更 (`0.1.0a2`)** — 座標系が **VRChat ウィンドウローカル** に一本化されました。`mouse.move(x, y)`（および `vrcpilot mouse move X Y`）はウィンドウローカル座標として解釈され、OCR / detect の結果もウィンドウローカルな `pos` のみを返します。従来の `display_pos.{polygon,bbox}` キーや、`OCRResult.display_polygon` / `display_bbox`（`DetectResult` 側も同様）は撤廃されました。OCR / detect の `pos.bbox`（あるいは `word.bbox` / `detection.bbox`）をそのまま `mouse.move` に渡せます。座標を手動で平行移動する必要はありません。

## 機能

- **プロセス制御** — Steam 経由で VRChat を起動 (`vrcpilot.launch`)。起動中プロセスの PID 検出と終了処理にも対応
- **ウィンドウ制御** — VRChat ウィンドウのフォーカス取得・解除、前面状態の確認に対応（Win32 / X11 / XWayland）
- **画面キャプチャ** — ストリーミング向けの `Capture` (mp4 / y4m シンク) と、YAML と相互変換できる単発キャプチャ `take_screenshot`
- **OCR** — 差し替え可能な `OCREngine` ABC と標準実装の `RapidOCREngine`。`ocr()` は単語単位の認識結果を VRChat ウィンドウローカル座標で返し、そのまま `mouse.move()` に渡せます
- **画像テンプレート検出** — OpenCV の `TM_CCOEFF_NORMED` を使う `TemplateDetectEngine`。OCR と同じ座標スキーマで検出結果を返します
- **合成入力** — keyboard / mouse の入力（Windows: [`pydirectinput`](https://github.com/learncodebygaming/pydirectinput) / Linux: [`inputtino`](https://github.com/games-on-whales/inputtino) + `/dev/uinput`）。VRChat にフォーカスがあるときだけ入力します
- **非 ASCII テキスト入力** — `vrcpilot.clipboard` がクリップボード + Ctrl+V 経由で任意の Unicode 文字列を入力
- **CLI フロントエンド** — `vrcpilot launch / screenshot / ocr / detect / mouse / keyboard / paste / capture / ...` の各サブコマンドを提供。`argcomplete` によるタブ補完にも対応

## インストール

Python 3.12 以上が必要です。

Linux では、`vrcpilot` をインストールする前に、同じ Python 環境へ `inputtino-python` を先にインストールしてください。ネイティブビルドに必要なシステムパッケージと `/dev/uinput` 権限は、後述の Linux の前提条件を参照してください。`uv tool install` は隔離環境を作るため、Linux では下の `--with inputtino-python` 付きの例を使ってください。

```bash
# Linux のみ: vrcpilot の前に inputtino をインストール
pip install "inputtino-python @ git+https://github.com/games-on-whales/inputtino.git@stable#subdirectory=bindings/python"
```

```bash
# ライブラリ + CLI
pip install vrcpilot

# OCR 機能込みでインストール
pip install "vrcpilot[ocr]"

# CLI ツールとして隔離環境にインストール
uv tool install vrcpilot

# Linux で CLI ツールとして隔離環境にインストール
uv tool install --with "inputtino-python @ git+https://github.com/games-on-whales/inputtino.git@stable#subdirectory=bindings/python" vrcpilot

# 開発用にソースからインストール
git clone https://github.com/MLShukai/vrcpilot
cd vrcpilot
uv sync --all-extras
```

> **プリリリース版** (`0.X.Yrc1`、`0.X.Ya1` など) は `pip install` のデフォルトでは選択されません。明示的にインストールするには `pip install --pre vrcpilot` または `uv tool install --prerelease=allow vrcpilot` を使ってください (上記の Linux 向け `uv tool install --with inputtino-python` パターンに対しても同様に `--prerelease=allow` を付与します)。

## プラットフォームごとの前提条件

### Windows

追加のシステムパッケージは不要です。`pywin32` と `pydirectinput` は依存関係として自動的にインストールされます。

### Linux

X11 または XWayland セッションが必要です。Wayland ネイティブセッションには対応していません。その環境では `focus()` / `unfocus()` が `RuntimeWarning` を出し、`False` を返します。

セッション種別は次のコマンドで確認できます。

```bash
echo $XDG_SESSION_TYPE   # x11 または wayland
echo $DISPLAY            # XWayland 経由でも値があれば OK
```

[`inputtino-python`](https://github.com/games-on-whales/inputtino/tree/stable/bindings/python) は git ソースからネイティブビルドされるため、`pip install` の前に次のシステムパッケージを入れておく必要があります。

```bash
sudo apt-get install -y cmake build-essential pkg-config libevdev-dev
sudo usermod -aG input "$USER"   # /dev/uinput への書き込み権限。一度ログアウトして再ログインすると反映
```

`uinput` カーネルモジュールが無効な場合は、`sudo modprobe uinput` で読み込んでください。

また、ディストリビューション名とインポート名が異なる点に注意してください。PyPI 上では `inputtino-python`、Python からは `inputtino` としてインポートします。

### macOS

対応していません。

## クイックスタート (CLI)

CLI は VRChat を操作する一番手軽な入口です。基本的な流れは、`screenshot` が `Screenshot` を YAML で出力し、`ocr` / `detect` が標準入力または `--screenshot` からそれを受け取る、という形です。

OCR / detect の結果はすべて **VRChat ウィンドウローカル座標** で `pos.bbox` に格納されます。`vrcpilot mouse move X Y` も同じウィンドウローカル座標を受け取るため、`pos.bbox` をそのまま渡せます。手動で座標を平行移動する必要はありません。

```bash
# VRChat をデスクトップモードで起動し、起動完了まで待機
vrcpilot launch --no-vr --screen-width 1280 --screen-height 720 --wait-timeout 60

# スクリーンショット → OCR → 可視化 PNG の保存をワンライナーで実行
vrcpilot screenshot | vrcpilot ocr --viz /tmp/viz.png > /tmp/ocr.yaml

# 同じパイプを画像テンプレート検出へ渡す例
vrcpilot screenshot | vrcpilot detect -q assets/button.png > /tmp/det.yaml

# マウス移動 + クリック (VRChat ウィンドウローカル座標)
vrcpilot mouse move 600 360
vrcpilot mouse click left

# キー押下 (--duration の既定値 0.1 秒は、VRChat が安定して受け取れる下限)
vrcpilot keyboard press w --duration 1.0

# 非 ASCII テキストを入力 (clipboard + Ctrl+V)
vrcpilot paste "こんにちは、VRChat！"

# 終了 (idempotent)
vrcpilot terminate
```

各オプションの詳細は `vrcpilot --help` および `vrcpilot <subcommand> --help` で確認できます。

## クイックスタート (Python API)

```python
from time import sleep

import vrcpilot

# launch() は VRChat の PID が見つかるまで最大 wait_timeout 秒 (既定値 30 秒) 待つ。
# None は、その時間内に VRChat を検出できなかったことを示す。
pid = vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)
if pid is None:
    raise RuntimeError("VRChat が launch() のタイムアウト内に起動しなかった")
sleep(45)  # 追加のウォームアップ待ち: シェーダー / アバターのロード / ネットワーク同期

try:
    # 1 枚だけキャプチャ (一時的な失敗時は None)
    shot = vrcpilot.take_screenshot()
    if shot is None:
        raise RuntimeError("VRChat の画面をキャプチャできなかった")

    # 表示中の単語をすべて OCR (engine 未指定時はキャッシュ済みの RapidOCREngine を使用)
    result = vrcpilot.ocr(shot)
    for word in result.words:
        print(word.text, word.bbox)

    # 最初の単語の中央へカーソルを移動して左クリック
    # word.bbox はウィンドウローカル座標で、mouse.move がそのまま受け取れる
    if result.words:
        x, y, w, h = result.words[0].bbox
        vrcpilot.mouse.move(int(x + w / 2), int(y + h / 2))
        vrcpilot.mouse.click(vrcpilot.MouseButton.LEFT)

    # キー押下
    vrcpilot.keyboard.press(vrcpilot.Key.W, duration=1.0)
finally:
    vrcpilot.terminate()
```

## CLI サブコマンド一覧

| サブコマンド | 用途                                                                                               |
| ------------ | -------------------------------------------------------------------------------------------------- |
| `launch`     | Steam 経由で VRChat を起動。`--no-vr` / `--screen-{width,height}` / `--wait-timeout` などに対応    |
| `pid`        | 起動中の VRChat の PID を 1 行 1 件で列挙                                                          |
| `terminate`  | VRChat を終了 (idempotent)                                                                         |
| `focus`      | VRChat ウィンドウを前面に出す                                                                      |
| `unfocus`    | VRChat ウィンドウを Z オーダーの最背面に送る                                                       |
| `screenshot` | 画面を 1 枚キャプチャし、`Screenshot` を YAML で標準出力へ出力 (PNG パスまたはインライン base64)   |
| `capture`    | 一定の FPS で録画。`-o file.mp4` 指定時はファイルに保存し、未指定時は y4m を標準出力へ出力         |
| `mouse`      | `move` / `click` / `scroll` (VRChat ウィンドウローカル座標)                                        |
| `keyboard`   | `press` (`--duration` の既定値は 0.1 秒)                                                           |
| `paste`      | クリップボード + Ctrl+V でテキストを入力 (非 ASCII 対応)                                           |
| `ocr`        | `Screenshot` YAML に対して OCR を実行 (標準入力のパイプ、または `--screenshot <path>`)             |
| `detect`     | `Screenshot` YAML に対してクエリ画像でテンプレート検索。`-q query.png` / `--threshold` / `--top-k` |

## シェル補完

`vrcpilot` は [`argcomplete`](https://pypi.org/project/argcomplete/) によるタブ補完に対応しています。補完できる対象は以下のとおりです。

- 各サブコマンド (`launch` / `pid` / `terminate` / `focus` / `unfocus` / `screenshot` / `capture` / `mouse` / `keyboard` / `paste` / `ocr` / `detect`)
- 各種オプション (`--steam-path` など)
- ファイルパスを取るオプション (`--steam-path` の `.exe`、`--query` の `.png` など)

### 前提条件

- `uv sync` で開発インストールするか、`uv tool install vrcpilot` でインストールし、`register-python-argcomplete` を PATH から実行できるようにしておくこと
- グローバルな PATH に追加したくない場合は、後述のコマンド中の `register-python-argcomplete ...` を `uv run register-python-argcomplete ...` に置き換えても構いません

### 一括セットアップ (開発リポジトリ向け)

クローン直後に「venv 作成 → activate → 補完登録」まで 1 行で済ませるには、リポジトリ同梱のブートストラップスクリプトを **source / dot-source** してください。

- bash: `. ./clicomp.sh`
- pwsh: `. .\CliComp.ps1`

スクリプトは以下を順に実行します。

1. 既存の `.venv` があれば activate する
2. `vrcpilot` が PATH になければ `just setup` を実行し、再度 activate する
3. `register-python-argcomplete` で現在のセッションに `vrcpilot` の補完を登録する

`bash clicomp.sh` や `.\CliComp.ps1` のようにサブシェルで実行すると、venv も補完設定も親シェルに残りません。必ず source / dot-source してください (通常実行された場合はスクリプト側で拒否します)。永続化する場合は、シェルの初期化ファイルに次の行を追記します。

```bash
# ~/.bashrc
. /path/to/vrcpilot/clicomp.sh
```

```powershell
# $PROFILE
. C:\path\to\vrcpilot\CliComp.ps1
```

### Bash / Git Bash

現在のセッションだけで有効にする場合:

```bash
eval "$(register-python-argcomplete vrcpilot)"
```

永続化する場合は、上記の 1 行を `~/.bashrc` (Git Bash 環境では `~/.bash_profile` でも構いません) に追記します。

### PowerShell

Windows PowerShell 5.1 と pwsh 7.x のどちらでも動作しますが、開発時は pwsh 7.x を推奨します。

現在のセッションだけで有効にする場合:

```powershell
register-python-argcomplete --shell powershell vrcpilot | Out-String | Invoke-Expression
```

永続化する場合は、PowerShell プロファイルに上記の `Invoke-Expression` 行を追記します。

```powershell
code $PROFILE   # notepad $PROFILE でも可
# 上記の Invoke-Expression 行をファイル末尾に追記して保存
# 新しいセッションを開くか、`. $PROFILE` で再読み込み
```

### トラブルシュート

補完がうまく動作しない場合は、argcomplete の公式ドキュメント <https://kislyuk.github.io/argcomplete/> を参照してください。

## ドキュメント

- **チュートリアル / プレイブック**: [`docs/usage.md`](docs/usage.md) — タスク別の解説 (起動 → 観測 → クリック → 後片付け)
- **CLI リファレンス**: [`docs/cli.md`](docs/cli.md) — 全サブコマンドのフラグと終了コードの一覧。`vrcpilot --help` / `vrcpilot <subcommand> --help` と同じ内容
- **Python API リファレンス**: [`docs/python-api.md`](docs/python-api.md) — `vrcpilot.<name>` で公開されている全シンボル
- **変更履歴**: [`CHANGELOG.md`](CHANGELOG.md)
- **コントリビュートガイド**: [`CONTRIBUTING.md`](CONTRIBUTING.md) (英語)

## ライセンス

[MIT](LICENSE) ライセンスで公開しています。
