# vrcpilot

[English](README.md) | **日本語**

[![PyPI](https://img.shields.io/pypi/v/vrcpilot?color=blue)](https://pypi.org/project/vrcpilot/)
[![Python](https://img.shields.io/pypi/pyversions/vrcpilot)](https://pypi.org/project/vrcpilot/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Test](https://github.com/MLShukai/vrcpilot/actions/workflows/test.yml/badge.svg)](https://github.com/MLShukai/vrcpilot/actions/workflows/test.yml)
[![Type Check](https://github.com/MLShukai/vrcpilot/actions/workflows/type-check.yaml/badge.svg)](https://github.com/MLShukai/vrcpilot/actions/workflows/type-check.yaml)
[![Format & Lint](https://github.com/MLShukai/vrcpilot/actions/workflows/pre-commit.yml/badge.svg)](https://github.com/MLShukai/vrcpilot/actions/workflows/pre-commit.yml)

VRChat を Python から自動操作するためのツールキットです (Windows / Linux に対応)。

## 機能

- **プロセス制御** — Steam 経由で VRChat の起動 (`vrcpilot.launch`)、起動中プロセスの PID 検出、終了処理
- **ウィンドウ制御** — ウィンドウのフォーカス取得・解除、前面状態の確認に対応（Win32 / X11 / XWayland）
- **画面キャプチャ** — ストリーミング用の `Capture` (mp4 / y4m sink) と、YAML で保存・復元できる `take_screenshot`
- **OCR** — 差し替え可能な `OCREngine` ABC と既定実装の `RapidOCREngine`。`ocr()` は単語ごとの認識結果をウィンドウローカル座標とデスクトップ絶対座標の両形式で返却
- **画像テンプレート検出** — OpenCV の `TM_CCOEFF_NORMED` を用いる `TemplateDetectEngine`。OCR と共通の座標スキーマで結果を返却
- **合成入力** — keyboard / mouse の入力（Windows: [`pydirectinput`](https://github.com/learncodebygaming/pydirectinput) / Linux: [`inputtino`](https://github.com/games-on-whales/inputtino) + `/dev/uinput`）。VRChat にフォーカスがある場合のみ入力するガード付き
- **非 ASCII テキスト入力** — `vrcpilot.clipboard` がクリップボード + Ctrl+V で任意の Unicode 文字列を入力
- **CLI フロントエンド** — `vrcpilot launch / screenshot / ocr / detect / mouse / keyboard / paste / capture / ...` の各サブコマンド。`argcomplete` によるタブ補完にも対応

## インストール

```bash
# ライブラリ + CLI (alpha 段階のため `--pre` が必要)
pip install --pre vrcpilot

# OCR extras 込みで導入
pip install --pre "vrcpilot[ocr]"

# CLI ツールとして隔離環境にインストール
uv tool install --prerelease=allow vrcpilot

# 開発用にソースから導入
git clone https://github.com/MLShukai/vrcpilot
cd vrcpilot
uv sync --all-extras
```

Python 3.12 以上が必須です。

## プラットフォームごとの前提条件

### Windows

追加のシステムパッケージは不要です。`pywin32` と `pydirectinput` は依存パッケージとして自動的に導入されます。

### Linux

X11 または XWayland セッションが必須です。Wayland ネイティブセッションには対応しておらず、その環境では `focus()` / `unfocus()` は `RuntimeWarning` を発して `False` を返します。

セッション種別は次のコマンドで確認できます。

```bash
echo $XDG_SESSION_TYPE   # x11 または wayland
echo $DISPLAY            # XWayland 経由でも値が入っていれば OK
```

[`inputtino-python`](https://github.com/games-on-whales/inputtino/tree/stable/bindings/python) は git ソースからネイティブビルドされるため、`pip install` の前に以下のシステムパッケージが必要です。

```bash
sudo apt-get install -y cmake build-essential pkg-config libevdev-dev
sudo usermod -aG input "$USER"   # /dev/uinput への書き込み権限。一度ログアウトして再ログインで反映
```

`uinput` カーネルモジュールが無効な場合は、`sudo modprobe uinput` で読み込んでください。

また、ディストリビューション名とインポート名が異なる点に注意してください。PyPI 上は `inputtino-python`、Python のインポート名は `inputtino` です。

### macOS

非対応です。

## クイックスタート (CLI)

CLI は VRChat を最も手早く操作する手段です。基本のパイプラインは、`screenshot` が `Screenshot` を YAML で出力し、`ocr` / `detect` が標準入力または `--screenshot` でそれを受け取る、という流れになります。

OCR / detect の結果をクリック対象にする場合は、**必ず `display_pos.bbox` を使ってください** (ウィンドウローカルの `pos` ではありません)。マルチモニタ環境やウィンドウ原点が画面左上にない環境では、`pos` をそのまま渡すと座標がずれます。

```bash
# VRChat をデスクトップモードで起動し、立ち上がるまで待機
vrcpilot launch --no-vr --screen-width 1280 --screen-height 720 --wait-timeout 60

# スクリーンショット → OCR → 可視化 PNG をワンライナーで実行
vrcpilot screenshot | vrcpilot ocr --viz /tmp/viz.png > /tmp/ocr.yaml

# 同じパイプを画像テンプレート検出に流す例
vrcpilot screenshot | vrcpilot detect -q assets/button.png > /tmp/det.yaml

# マウス移動 + クリック (デスクトップ絶対座標)
vrcpilot mouse move 1183 514
vrcpilot mouse click left

# キー押下 (--duration の既定値 0.1 秒は VRChat が安定して受け取れる下限)
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

# launch() は VRChat の PID を最大 wait_timeout 秒 (既定値 30 秒) 待って返す。
# None は、その時間内に VRChat を検出できなかったことを示す。
pid = vrcpilot.launch(no_vr=True, screen_width=1280, screen_height=720)
if pid is None:
    raise RuntimeError("VRChat が launch() のタイムアウト内に起動しなかった")
sleep(45)  # 追加のウォームアップ待ち: シェーダ / アバターのロード / ネットワーク同期

try:
    # 1 枚キャプチャ (一時的な失敗時は None)
    shot = vrcpilot.take_screenshot()
    if shot is None:
        raise RuntimeError("VRChat の画面をキャプチャできなかった")

    # 認識可能な全単語を OCR (engine 未指定時はキャッシュ済みの RapidOCREngine を使用)
    result = vrcpilot.ocr(shot)
    for word in result.words:
        print(word.text, result.display_bbox(word))

    # 先頭の単語の中央へカーソル移動 + 左クリック
    if result.words:
        x, y, w, h = result.display_bbox(result.words[0])
        vrcpilot.mouse.move(int(x + w / 2), int(y + h / 2))
        vrcpilot.mouse.click(vrcpilot.MouseButton.LEFT)

    # キー押下
    vrcpilot.keyboard.press(vrcpilot.Key.W, duration=1.0)
finally:
    vrcpilot.terminate()
```

## CLI サブコマンド一覧

| サブコマンド | 用途                                                                                            |
| ------------ | ----------------------------------------------------------------------------------------------- |
| `launch`     | Steam 経由で VRChat を起動。`--no-vr` / `--screen-{width,height}` / `--wait-timeout` などに対応 |
| `pid`        | 起動中の VRChat の PID を 1 行 1 件で列挙                                                       |
| `terminate`  | VRChat を強制終了 (idempotent)                                                                  |
| `focus`      | VRChat ウィンドウを前面に表示                                                                   |
| `unfocus`    | VRChat ウィンドウを Z オーダーの最背面に送る                                                    |
| `screenshot` | 画面を 1 枚キャプチャし、`Screenshot` を YAML で出力 (PNG パスまたはインライン base64)          |
| `capture`    | 一定 FPS で録画。`-o file.mp4` 指定時はファイル保存、未指定時は y4m を標準出力                  |
| `mouse`      | `move` / `click` / `scroll` (デスクトップ絶対座標)                                              |
| `keyboard`   | `press` (`--duration` の既定値 0.1 秒)                                                          |
| `paste`      | クリップボード + Ctrl+V でテキストを入力 (非 ASCII 対応)                                        |
| `ocr`        | `Screenshot` YAML に対して OCR を実行 (標準入力パイプ または `--screenshot <path>`)             |
| `detect`     | `Screenshot` YAML 内をクエリ画像でテンプレート検索。`-q query.png` / `--threshold` / `--top-k`  |

## シェル補完

`vrcpilot` は [`argcomplete`](https://pypi.org/project/argcomplete/) によるタブ補完に対応します。補完対象は以下のとおりです。

- 各サブコマンド (`launch` / `pid` / `terminate` / `focus` / `unfocus` / `screenshot` / `capture` / `mouse` / `keyboard` / `paste` / `ocr` / `detect`)
- 各種オプション (`--steam-path` など)
- ファイルパスを取るオプション (`--steam-path` の `.exe`、`--query` の `.png` など)

### 前提条件

- `uv sync` で開発インストールするか、`uv tool install --prerelease=allow vrcpilot` で取得し、`register-python-argcomplete` を PATH に通しておくこと
- PATH を汚したくない場合は、後述するコマンド中の `register-python-argcomplete ...` を `uv run register-python-argcomplete ...` に置き換えても可

### ワンショットセットアップ (開発リポジトリ向け)

クローン直後に「venv 作成 → activate → 補完登録」を 1 行で済ませたい場合は、リポジトリ同梱のブートストラップスクリプトを **source / dot-source** してください。

- bash: `. ./clicomp.sh`
- pwsh: `. .\CliComp.ps1`

スクリプトは以下を順に実行します。

1. `.venv` が存在すれば activate する
2. `vrcpilot` が PATH に無ければ `just setup` を実行し、改めて activate する
3. `register-python-argcomplete` で現セッションに `vrcpilot` の補完を登録する

サブシェルで起動した場合 (`bash clicomp.sh` や `.\CliComp.ps1` のように実行した場合) は、venv も補完も親シェルに残らないため、必ず source / dot-source してください (そのまま実行された場合はスクリプト側で拒否します)。永続化したい場合は、シェルの初期化ファイルに以下を追記します。

```bash
# ~/.bashrc
. /path/to/vrcpilot/clicomp.sh
```

```powershell
# $PROFILE
. C:\path\to\vrcpilot\CliComp.ps1
```

### Bash / Git Bash

現在のセッションでのみ有効化する場合:

```bash
eval "$(register-python-argcomplete vrcpilot)"
```

永続化する場合は、上記の 1 行を `~/.bashrc` (Git Bash 環境では `~/.bash_profile` でも可) に追記します。

### PowerShell

Windows PowerShell 5.1 と pwsh 7.x のいずれでも動作しますが、開発時は pwsh 7.x を推奨します。

現在のセッションでのみ有効化する場合:

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

補完が動作しない場合は、argcomplete の公式ドキュメント <https://kislyuk.github.io/argcomplete/> を参照してください。

## ドキュメント

- **チュートリアル / プレイブック**: [`docs/usage.md`](docs/usage.md) — タスク指向の解説 (起動 → 観測 → クリック → 後片付け)
- **CLI リファレンス**: [`docs/cli.md`](docs/cli.md) — 全サブコマンドのフラグと終了コードの一覧。`vrcpilot --help` / `vrcpilot <subcommand> --help` と同じ内容
- **Python API リファレンス**: [`docs/python-api.md`](docs/python-api.md) — `vrcpilot.<name>` で公開している全シンボル
- **変更履歴**: [`CHANGELOG.md`](CHANGELOG.md)
- **コントリビュートガイド**: [`CONTRIBUTING.md`](CONTRIBUTING.md) (英語)

## ライセンス

[MIT](LICENSE) ライセンスのもとで公開しています。
