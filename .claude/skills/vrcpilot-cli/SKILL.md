---
name: vrcpilot-cli
description: vrcpilot CLI (uv run vrcpilot ...) のサブコマンド表、screenshot → ocr / detect 標準パイプライン、record で映像/音声/両方を MP4 / WAV / MKV self-describing stdout に流す典型例、osc 7 アクションの典型例、OCR/detect/mouse の座標系（すべて VRChat window-local）。CLI を実行する／引数を組み立てる／パイプラインを書く前に読む
---

# vrcpilot CLI 参照リファレンス

`uv run vrcpilot <subcommand> ...` で起動する PEP 723 console-script。
詳細は各サブコマンドの `--help` または `src/vrcpilot/cli/<name>.py` の docstring。

## サブコマンド一覧

| サブコマンド | 用途                                                                                                   | 状態系の出力                                                                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `launch`     | Steam 経由で VRChat を起動。`--no-vr` / `--screen-{width,height}` / `--osc-in-port` / `--wait-timeout` | stdout に PID（待機完了時）、`--wait-timeout 0` で即時 return                                                            |
| `pid`        | 動作中 VRChat の PID 一覧                                                                              | 1 行 1 PID。誰もいなければ exit 1                                                                                        |
| `terminate`  | VRChat を強制終了（idempotent）                                                                        | 殺した PID のみ stdout、対象なしは無音で exit 0                                                                          |
| `focus`      | VRChat ウィンドウを前面に                                                                              | 成功は無音、失敗は stderr 1 行                                                                                           |
| `unfocus`    | VRChat ウィンドウを z-order 末尾に                                                                     | 同上                                                                                                                     |
| `screenshot` | 1 枚撮って `Screenshot` を YAML で吐く                                                                 | `-o <path>` で PNG を書き出し YAML に `path:` を、未指定で base64 PNG を埋め込む（`image:`）                             |
| `record`     | VRChat の映像 / 音声を録画。`--video` / `--audio` でモード選択（両方 / 未指定はどちらも記録）          | `-o file.mp4` (映像 / 両方) または `-o file.wav` (音声のみ)。`-o` 未指定で self-describing MKV を stdout（TTY なら拒否） |
| `mouse`      | `move` / `click` / `scroll`（`press` / `release` は意図的に未公開）                                    | guard 失敗で exit 1                                                                                                      |
| `keyboard`   | `press` のみ公開（`down` / `up` をプロセスに跨いで持てないため）                                       | `--duration` のデフォルト 0.1（VRChat に届く下限。0.0 にしない）                                                         |
| `paste`      | クリップボード経由で文字列を Ctrl+V 投入（非 ASCII 用）                                                | 引数 or stdin から読む。tty かつ引数なしは exit 2                                                                        |
| `ocr`        | `Screenshot` を入力に RapidOCR を回し、認識単語を YAML で返す                                          | `--viz` で bbox 重ね PNG。**`--screenshot` か stdin pipe が必須**                                                        |
| `detect`     | `Screenshot` 内をクエリ画像でテンプレート検索                                                          | `-q <png>` 必須。`--threshold` / `--top-k` / `--viz`。同じく入力 YAML 必須                                               |
| `osc`        | VRChat OSC 送信 (`send` / `axis` / `tap` / `hold` / `chatbox` / `typing` / `avatar` の 7 アクション)   | 成功は無音。range / name 違反で exit 1、`chatbox` は tty かつ引数なしで exit 2                                           |

## 標準パイプライン（重要）

`vrcpilot ocr` と `vrcpilot detect` は **自身でスクリーンショットを撮らない**
（過去にあった live capture は `feat(cli)!: ocr/detect の自動 live capture 経路を廃止` で削除）。`vrcpilot screenshot` の出力 YAML を pipe するか、
`--screenshot <yaml>` で渡すこと。

```bash
# (1) インライン base64 を pipe（一番短い形）
uv run vrcpilot screenshot | uv run vrcpilot ocr --viz /tmp/viz.png > /tmp/ocr.yaml

# (2) PNG を残しつつ pipe（後で目視確認したいとき）
uv run vrcpilot screenshot -o /tmp/shot.png | uv run vrcpilot ocr > /tmp/ocr.yaml

# (3) 既存の YAML を再利用
uv run vrcpilot screenshot -o /tmp/shot.png > /tmp/shot.yaml
uv run vrcpilot detect -q ./assets/button.png --screenshot /tmp/shot.yaml > /tmp/det.yaml
```

`vrcpilot screenshot` 単体も挙動が 2 系統ある:

- `-o <path>` あり: PNG を書き出し、YAML には `path:` で絶対パスを記録（履歴を残す pipeline 向け）
- `-o` なし（デフォルト）: PNG ファイルは作らず、YAML 内 `image:` に base64 PNG を埋め込む（pipe で消費する想定）

## 録画 (`record`)

`vrcpilot record` は VRChat の映像 / 音声 / 両方を統合的に録画する。
映像は `Capture` と同じく focus-free（Win32 WGC / X11 Composite）で取得し、
音声は `proc-tap` (Windows / macOS) または PipeWire (Linux) 経由で
**VRChat の音だけ** を抽出する（Discord / OBS / 他アプリは混ざらない）。

モードは `--video` / `--audio` フラグで決まる（両方付与 or どちらも無しは
`both`）。`-o` 指定時は拡張子がモードと一致しないと exit 2。

```
vrcpilot record [-o PATH] [--video] [--audio] [--fps FLOAT] [--duration SECONDS]
```

| `--video` | `--audio` | mode    | 必須拡張子 |
| --------- | --------- | ------- | ---------- |
| なし      | なし      | `both`  | `.mp4`     |
| あり      | なし      | `video` | `.mp4`     |
| なし      | あり      | `audio` | `.wav`     |
| あり      | あり      | `both`  | `.mp4`     |

- `-o PATH` がディレクトリなら `<dir>/vrcpilot_record_<YYYYMMDD_HHMMSS>.{mp4,wav}`
  を内部で組み立てる
- `-o` 未指定なら **モードに関わらず常に self-describing MKV (matroska,
  libx264 + AAC)** を stdout に流す。TTY 出力は exit 1
- `--fps` の既定値は 30.0。`--audio` 単独で `--fps` を渡すと exit 2
- 進捗メッセージは常に stderr、stdout はファイルモードで絶対パス 1 行、
  pipe モードで MKV バイト列のみが流れる（パイプ整合性を担保）

```bash
# 映像 + 音声 MP4 を 10 秒
uv run vrcpilot record -o /tmp/vrc.mp4 --duration 10

# 映像のみ MP4
uv run vrcpilot record --video -o /tmp/vrc_video.mp4 --duration 10

# 音声のみ WAV
uv run vrcpilot record --audio -o /tmp/vrc_audio.wav --duration 10

# 自己記述 MKV を stdout に流して ffmpeg に直接渡す
uv run vrcpilot record --duration 5 | ffmpeg -i - -c copy /tmp/vrc.mkv

# Ctrl+C 停止モード（duration 無し）
uv run vrcpilot record -o /tmp/vrc.mp4
```

VRChat 未起動 / フレーム or サンプルがゼロ件 / pipe で TTY のいずれかは
exit 1。引数不整合（拡張子ミスマッチ、`--fps` + `--audio` 単独）は exit 2。

## OSC コマンドの典型例

`vrcpilot osc` は VRChat の OSC API を CLI から叩くための入口。接続パラメータ
(`--host` / `--port` / `--button-hold`) は親 `osc` の直後に書き、アクションは
その後ろに置く (`vrcpilot osc --host 192.168.1.10 tap jump` の順)。送信専用で
listen 系は未提供、`OscSender.send` の任意 Python 値パススルーは Python API
側のエスケープハッチに留めて CLI 非公開（`send` サブアクションは `--bool` /
`--int` / `--float` の必須 mutex で型を明示する）。

```bash
# 入力コントローラ系: tap (1 -> sleep --button-hold -> 0)
uv run vrcpilot osc tap jump
uv run vrcpilot osc tap quick-menu-toggle-left

# axis (-1.0..1.0 連続値)
uv run vrcpilot osc axis vertical 0.5
uv run vrcpilot osc axis vertical 0.0          # release

# hold (押下/解放を明示)
uv run vrcpilot osc hold run on
uv run vrcpilot osc hold run off

# chatbox: 位置引数 or stdin
uv run vrcpilot osc chatbox "hello world" --no-sfx
echo "from pipe" | uv run vrcpilot osc chatbox

# typing インジケータ
uv run vrcpilot osc typing on && sleep 1 && uv run vrcpilot osc typing off

# avatar parameters (型は --bool / --int / --float の必須 mutex)
uv run vrcpilot osc avatar MyParam --float 0.7
uv run vrcpilot osc avatar MyToggle --bool true

# 送信先を変える (例: 異なるホスト / ポートに転送)
uv run vrcpilot osc --host 192.168.1.10 --port 9100 tap jump

# 低レベル escape hatch (任意 OSC アドレスへ型付き送信)
uv run vrcpilot osc send /custom/Address --int 42
```

## 座標系

OCR / detect / mouse はすべて **VRChat window-local** で統一されている
（左上 origin、単位はピクセル）:

- `pos.{polygon,bbox}`: ウィンドウローカル座標。これだけが出力される
- `vrcpilot mouse move <x> <y>` の `<x> <y>` も window-local として解釈される
- したがって `pos.bbox` 中心を `mouse move` にそのまま渡せる
  （`[x, y, w, h]` なら `(x + w/2, y + h/2)`）
- マルチモニタや非原点ウィンドウでも、`mouse` 側がランタイムで現在の
  ウィンドウ位置を解決して desktop 絶対に変換するため追加の補正不要

旧 `display_pos.{polygon,bbox}` キーは 2026-05-22 に廃止された。
`Screenshot.x` / `Screenshot.y`（撮影時のウィンドウのデスクトップ位置）は
情報として YAML に残るが、`mouse move` の引数には不要

## 実機 end-to-end の playbook

VRChat を実際に操作するシナリオ（起動 → メニュー → OCR → click → 移動 →
terminate）は [memory/feedback_vrchat_cli_playbook.md](../../../memory/feedback_vrchat_cli_playbook.md)
を参照。
