# tests/e2e

実 VRChat を起動して end-to-end の振る舞いを確認するためのスクリプト群。

## 目的

`tests/` 配下の通常のユニットテストは `pytest` で完結する高速・自動な検証だが、
`vrcpilot` は最終的に実 VRChat プロセスを起動・操作・終了する必要があり、その
経路はモックでは検証しきれない。本ディレクトリのスクリプトは、実機で VRChat
を起こして PID を確認し、`terminate` まで通すことで、ライブラリ全体が本物の
環境で期待通り動くことを人間または Claude Code が確かめるための入口である。

各スクリプトは終了時に必ず以下のいずれかを標準出力へ出す。

- `PASS: <name>` (exit code 0)
- `FAIL: <name>: <reason>` (exit code 1)

これにより、自走中の Claude Code でもユーザーでも、出力 1 行で成否を判別でき
る。

## 前提条件

- Windows / Linux のどちらでも実行可能（Linux では direct-spawn 用に
  `umu-launcher` が必要。詳細は [README.md](../../README.md) を参照）。
- VRChat と Steam がインストール済みで、Steam にログイン済みであること。
- `just setup` 済みで `uv` 環境が整っていること。
- `mic` シナリオを使う場合は、Windows なら VB-Audio Virtual Cable、Linux
  なら `vrcpilot linux-mic register` 済みの `VRCPilotMic` シンクが必要。

## 警告

スクリプトを実行すると、その時点で起動している VRChat セッションが pre-cleanup
で強制終了される。VRChat を使った作業中には実行しないこと。各シナリオは
post-cleanup でも VRChat を落とすため、終了後の環境はクリーンな状態に戻る。

## 実行方法

`just` レシピを使うのが標準。引数なしで全シナリオを順に実行する。

```sh
just e2e-test                       # 全シナリオを順に実行
just e2e-test launch_terminate      # 単一シナリオを指定
just e2e-test cli_launch_terminate
just e2e-test launch_no_vr
just e2e-test focus_unfocus
just e2e-test screenshot
```

直接実行も可能。

```sh
uv run python tests/e2e/all.py
uv run python tests/e2e/launch_terminate.py
```

## シナリオ一覧

### ランチャ系

| 名前                   | 内容                                                                                                                                                                                                                                                                                                 |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `all`                  | 同ディレクトリ内の全シナリオを subprocess で順に実行し、PASS/FAIL を集約する                                                                                                                                                                                                                         |
| `launch_terminate`     | API (`vrcpilot.launch` / `find_pid` / `terminate`) のハッピーパス                                                                                                                                                                                                                                    |
| `launch_via_steam`     | `vrcpilot.launch(via_steam=True)` の従来 Steam 経由ルートを検証 (default が direct-spawn に変わった後の保険)                                                                                                                                                                                         |
| `launch_no_vr`         | `vrcpilot.launch(no_vr=True)` のデスクトップモード起動を確認 (HMD 非装着想定)                                                                                                                                                                                                                        |
| `cli_launch_terminate` | `uv run vrcpilot` の `launch` / `pid` / `terminate` を subprocess で叩く CLI 経路の検証                                                                                                                                                                                                              |
| `multi_instance`       | `profile=0` と `profile=1` で 2 インスタンスを並走させ、複数 PID 系 API 契約 (`find_pids` newest-first / `VRChatMultipleInstancesError` / `VRChatAlreadyRunningError` / 個別 `terminate(pid)`) を検証する。Linux は profile ごとに wineprefix が auto-gen されるため初回は Proton 初期化で数分かかる |

### ウィンドウ・画面

| 名前            | 内容                                                                                                                                                             |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `focus_unfocus` | `vrcpilot.focus()` / `unfocus()` を交互に呼び、各操作後の screenshot を `_e2e_artifacts/focus_unfocus/<YYYYMMDD_HHMMSS>/` 配下へ保存して目視確認できるようにする |
| `screenshot`    | `vrcpilot.take_screenshot()` が VRChat ウィンドウのみを切り出していること (デスクトップ背景や他アプリが混入していないこと) を確認                                |
| `capture`       | `vrcpilot.CaptureLoop` を 30fps で駆動し、e2e ローカルの PyAV writer 経由で MP4 を保存しつつ per-frame interval を記録                                           |

### 認識系

| 名前     | 内容                                                                                                                                |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `ocr`    | LaunchPad を開いた状態で `vrcpilot.ocr()` を実行し、text-rich な panel に対して既定の `RapidOCREngine` がワード抽出できることを確認 |
| `detect` | LaunchPad の各アイコンを `tests/e2e/fixtures/detect_icons/` の PNG で template-search し、全アイコンの検出可否をチェック            |

### 合成入力

| 名前        | 内容                                                                                                                                       |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `mouse`     | `move` / `click` / `press` + `release` / `scroll` / variadic combo (`click(LEFT, RIGHT)`) を順に呼び、`ensure_target` guard 経路も検証する |
| `keyboard`  | ESC で LaunchPad を toggle した上で、`down/press/up` triplet と `press(SHIFT_LEFT, A)` 短縮形の挙動を交互ステップで検証                    |
| `clipboard` | `vrcpilot.clipboard.paste("...")` で日本語文字列をチャット入力欄へ流し込み、screenshot で目視可能にする                                    |

### 音声・OSC

| 名前      | 内容                                                                                                                                                                                                                        |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `speaker` | `vrcpilot.speaker.SpeakerLoop` を駆動し、proc-tap (Windows) / PipeWire (Linux) からの WAV 出力 + RMS をチェック (CLI 非依存)                                                                                                |
| `mic`     | `vrcpilot.Mic` をサインで駆動し、Windows なら `CABLE Input` -> `CABLE Output`、Linux なら `VRCPilotMic` null-sink -> monitor をループバック確認する。**VRChat を起動しない例外的なシナリオ** (mic 出力単独の経路だけを検証) |
| `osc`     | VRChat 内蔵の OSC Debug Panel を trinket で固定し、`OscSender` から送った `/input/*` / `/avatar/parameters/*` がパネル上のラインとして可視化されていることを screenshot で確認                                              |

### 録画 CLI (外部 ffmpeg / ffprobe 必須)

| 名前                      | 内容                                                                                                                                                                                                                                                                                     |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cli_record_ffmpeg`       | `vrcpilot record --audio` を 2 出力経路で検証: (A) `-o <wav>` 直接保存 → `wave.open` で 48 kHz / stereo / 16-bit + RMS dBFS を確認、(B) stdout の自己記述 MKV を `ffmpeg -i - -c:a pcm_s16le` にパイプして WAV 再エンコード → `ffprobe` で pcm_s16le / 48 kHz / stereo / duration を確認 |
| `cli_record_video_ffmpeg` | `vrcpilot record --video` の stdout MKV を `ffmpeg` にパイプして `.mp4` に `-c:v copy`。`ffprobe` で video stream が 1 本、audio stream が 0 本であることを確認                                                                                                                          |
| `cli_record_av_ffmpeg`    | `vrcpilot record` の既定 (映像 + 音声) `-o <mp4>` ファイル出力経路。stream-mode 版は `cli_record_video_ffmpeg` / `cli_record_ffmpeg` がカバー                                                                                                                                            |

## 実行時間の目安

各シナリオおよそ 30 秒前後。内訳は PID 検出 (~数秒) + warmup (15-20 秒) +
terminate / cleanup (数秒) 程度。

## アーティファクト出力レイアウト

screenshot や録画などのアーティファクトは `_e2e_artifacts/<scenario>/<YYYYMMDD_HHMMSS>/<label>.<ext>`
の形式で出力される。同じシナリオを複数回流すと、scenario ディレクトリ配下に
複数の timestamp ディレクトリが並ぶため、過去の実行結果が上書きされない。
1 回のシナリオ実行内で複数のアーティファクトを書き出す場合は、それらすべて
が同じ timestamp ディレクトリにまとまる (各実行ごとに 1 ディレクトリ)。

## CLI 経路をどこまで e2e に置くか

CLI mirror は **CLI でしか検証できない契約があるサブコマンドだけ** e2e に置く。

- 既存の CLI e2e:
  - `cli_launch_terminate` — `pid=$(vrcpilot launch)` 等 shell pipeline 向けの
    stdout / exit-code 契約
  - `cli_record_*` — stdout への自己記述 MKV/WAV + 外部 `ffmpeg` への pipe 契約
- それ以外（`focus` / `unfocus` / `screenshot` / `mouse` / `keyboard` / `paste` /
  `ocr` / `detect` / `osc` / `mic` / `linux-mic`）の CLI 経路は e2e mirror を
  作らない:
  - argparse 解析・stdout 整形・API 委譲は `tests/vrcpilot/cli/` の unit test
    がカバー済み
  - API 経路の e2e で実 VRChat / 実デバイスとの結合はすでに検証済み
  - 全サブコマンドを 1:1 で mirror するとシナリオ数・実行時間が倍近くなる
    割に追加カバレッジが薄い

新しい CLI サブコマンドを足すときも、同じ問いを立てる:
「unit test と API e2e の組み合わせで証明できない契約があるか?」 ある場合のみ
mirror を追加する。

## CI への影響

`pyproject.toml` の pytest 設定で `--ignore=tests/e2e` を指定しているため、
`just test` および CI の pytest 収集対象から除外される。実機を要する end-to-end
の動作確認スクリプトという位置付け。
