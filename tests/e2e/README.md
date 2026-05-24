# tests/e2e

実 VRChat を起動して end-to-end の振る舞いを確認するためのスクリプト群。

## 目的

`tests/` 配下の通常のユニットテストは `pytest` で完結する高速・自動な検証だが、
`vrcpilot` は最終的に Steam 経由で実 VRChat プロセスを起動・終了する必要があ
り、その経路はモックでは検証しきれない。本ディレクトリのスクリプトは、実機で
VRChat を起こして PID を確認し、`terminate` まで通すことで、ライブラリ全体が
本物の環境で期待通り動くことを人間または Claude Code が確かめるための入口で
ある。

各スクリプトは終了時に必ず以下のいずれかを標準出力へ出す。

- `PASS: <name>` (exit code 0)
- `FAIL: <name>: <reason>` (exit code 1)

これにより、自走中の Claude Code でもユーザーでも、出力 1 行で成否を判別でき
る。

## 前提条件

- Windows 環境を想定（launcher が動作すれば Linux でも実行可能）。
- VRChat と Steam がインストール済みで、Steam にログイン済みであること。
- `just setup` 済みで `uv` 環境が整っていること。

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

| 名前                   | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `all`                  | 同ディレクトリ内の全シナリオを subprocess で順に実行し、PASS/FAIL を集約する。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `launch_terminate`     | API (`vrcpilot.launch` / `find_pid` / `terminate`) のハッピーパス。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `cli_launch_terminate` | `uv run vrcpilot` の `launch` / `pid` / `terminate` を subprocess で叩く CLI 経路の検証。                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `launch_no_vr`         | `vrcpilot.launch(no_vr=True)` でデスクトップモード起動を確認。HMD 非装着のマシンでも動く想定。                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `focus_unfocus`        | `vrcpilot.focus()` で最前面化、`vrcpilot.unfocus()` で z-order 最下層化。各操作後に `_e2e_artifacts/` へスクリーンショットを保存し、Claude / 人間が目視確認する。                                                                                                                                                                                                                                                                                                                                                                                                           |
| `screenshot`           | `vrcpilot.take_screenshot()` で VRChat ウィンドウだけのスクリーンショットが取れることを確認。1280x720 で起動した VRChat に対して撮影し、`_e2e_artifacts/screenshot_vrchat_<timestamp>.png` にウィンドウのみが写った PNG が保存される（デスクトップ背景や他アプリが混入していないこと）。                                                                                                                                                                                                                                                                                    |
| `cli_record_ffmpeg`    | `uv run vrcpilot record --audio` の 2 出力経路を end-to-end 検証する。Step A は `-o <wav>` モードで保存され、`wave.open` で 48 kHz / stereo / 16-bit を確認し RMS dBFS をログ。Step B は stdout の自己記述 MKV を `ffmpeg -i - -c:a pcm_s16le` にパイプして WAV へ再エンコードし、`ffprobe` で `pcm_s16le` / 48 kHz / stereo / duration を確認する。                                                                                                                                                                                                                        |
| `multi_instance`       | `vrcpilot.launch(profile=0, no_vr=True)` と `profile=1` で 2 インスタンスを並走させ、複数 PID 系の API 契約を検証する。`find_pids()` が newest-first で両 PID を返すこと、`resolve_pid(None)` が `VRChatMultipleInstancesError` を raise し `.pids` に両方を含むこと、`launch(via_steam=True)` が `VRChatAlreadyRunningError` で fail-fast し既存 PID を改変しないこと、`terminate(pid_a)` が選択 kill し `terminate()` が残りを全 kill することを順に確認する。Linux は profile ごとに wineprefix が auto-gen されるため、初回実行は Proton 初期化で数分かかることがある。 |

## 実行時間の目安

各シナリオおよそ 30 秒前後。内訳は PID 検出 (~数秒) + warmup (15-20 秒) +
terminate / cleanup (数秒) 程度。

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
  - 全 14 サブコマンドを 1:1 で mirror するとシナリオ数・実行時間が倍近くなる
    割に追加カバレッジが薄い

新しい CLI サブコマンドを足すときも、同じ問いを立てる:
「unit test と API e2e の組み合わせで証明できない契約があるか?」 ある場合のみ
mirror を追加する。

## CI への影響

`pyproject.toml` の pytest 設定で `--ignore=tests/e2e` を指定しているため、
`just test` および CI の pytest 収集対象から除外される。実機を要する end-to-end
の動作確認スクリプトという位置付け。
