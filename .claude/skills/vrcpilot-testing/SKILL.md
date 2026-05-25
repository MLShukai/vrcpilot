---
name: vrcpilot-testing
description: vrcpilot のテスト戦略。real-resource を最優先し、自前 ABC のみ fake 可、3rd-party ライブラリ表面 (pulsectl / soundcard / subprocess.Popen / psutil / Xlib / windows_capture / time.sleep 等) のモックは禁止。4 区分 (unit / integration-with-fakes / integration-real / e2e)、tests ミラーレイアウト、書いてはいけないテスト、公開 API 契約ピン例外、Xvfb / PipeWire null-sink / loopback UDP / tempfile、mutation testing、Windows cp932 と Linux SSH e2e の実行環境クセ。テストコードを書く／壊れた e2e を調査する／pytest 周りを設定する前に読む
---

# vrcpilot テスト方針リファレンス

本 skill は手元で書き始める前にざっと読む「実行可能なまとめ」として位置づける。
背景となる学びの蓄積は [memory/](../../../memory/) 配下のファイル群に集約されている。

## 哲学

vrcpilot は OS / 3rd-party ライブラリ結合が支配的なライブラリ。「動くテスト」
ではなく「**実環境の振る舞いを保証するテスト**」を優先する。

3rd-party ライブラリの表面をミラーした fake は、その挙動に対する**自分の
仮定**をテストするだけで、上流変更を検出できない (GOOS / Freeman & Pryce:
"Don't mock what you don't own")。fake が drift して CI 緑でも実機で死ぬ
事故を防ぐため、**実 resource を最優先**とする。

### 検証対象の優先順位

1. **実 resource** — `tmp_path` で実 file I/O、実 subprocess の
   `sleep` / `echo`、loopback UDP で OSC、Xvfb で X11、PipeWire null-sink
   で audio、実 PNG fixture を実 OpenCV / RapidOCR に通す
2. **自前 ABC の fake** — vrcpilot が自分で定義した抽象 (`OCREngine`,
   `DetectEngine`, `Capture` / `CaptureLoop`, `Mic`, `Speaker` /
   `SpeakerLoop`, `OscSender` 等) の差し替え。**所有しているもの**は OK
3. **3rd-party 表面のモック → 禁止**: `pulsectl.Pulse`, `soundcard.*`,
   `subprocess.Popen`, `psutil.process_iter` / `psutil.Process`,
   `windows_capture.WindowsCapture`, `Xlib.display.Display`,
   `pyperclip.copy`, `proctap.*`, `inputtino.*`, `pydirectinput.*`,
   `time.sleep` 等。必要なら integration-real に分類する
4. **自分のコードの内部関数モック → 禁止**:
   `vrcpilot.controls.*.ensure_target`, `vrcpilot.process.pid.find_pids`
   のような内部関数を直接 `mocker.patch` で置き換える行為。リファクタで
   壊れるだけで何も保証しない

## 基本原則

- 必要十分なテストのみを記述する。過剰なテストは避ける
- 内部実装の詳細はテストしない。公開インターフェースと振る舞いをテストする
- テスト関数に戻り値の型アノテーションは不要
- **コードカバレッジは診断であり目標ではない**。Fowler:
  *"high coverage numbers are too easy to reach with low quality testing"*。
  100% は赤信号

## テストレイアウト

`tests/` は `src/vrcpilot/` の構造を 1 対 1 でミラーリングする:

- `src/vrcpilot/foo.py` ↔ `tests/vrcpilot/test_foo.py`
- `src/vrcpilot/__init__.py` ↔ `tests/vrcpilot/test_init.py`
- `src/vrcpilot/sub/bar.py` ↔ `tests/vrcpilot/sub/test_bar.py`
- `tests/` 直下に置くのは `__init__.py` / `helpers.py` / `conftest.py` /
  `manual/` のみ
- 1 ファイル 1 テストを原則とし、`window/{windows,linux}.py` のように
  バックエンド分割されているソースはテストも分けて 1 対 1 を維持する

詳細: [memory/feedback_test_layout_mirror.md](../../../memory/feedback_test_layout_mirror.md)

## テスト 4 区分

| 区分                       | 配置                                                                              | 検証対象                                                  | モック許容                                                       |
| -------------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------- |
| **unit**                   | `tests/vrcpilot/test_<file>.py`                                                   | 純粋ロジック (OSC 符号化、geometry、OCR 後処理、座標変換) | なし                                                             |
| **integration-with-fakes** | 同上、`tests/fakes/` から **自前 ABC** の fake を import                          | モジュール間結合 (ABC 越し)                               | **自前 ABC のみ** (`FakeCapture`, `FakeOCREngine`, `FakeMic` 等) |
| **integration-real**       | `test_<windows\|linux>.py`、`window/test_*`、`capture/test_{windows,linux}.py` 等 | adapter / 3rd-party 結合点 (実環境)                       | 原則なし。実 daemon / Xvfb / loopback / 実 subprocess / 実 PNG   |
| **e2e**                    | `tests/e2e/`                                                                      | end-to-end (実 VRChat)                                    | なし                                                             |

新規テストを書く前に区分を決める。3rd-party モックが必要に見えたら
integration-real に分類できないか先に検討する。

### integration-real の典型パターン

| 領域                  | real resource                                                                   |
| --------------------- | ------------------------------------------------------------------------------- |
| filesystem            | `tmp_path` / `tmp_path_factory` (pytest 組込)                                   |
| subprocess            | `python -c "import time; time.sleep(0.1)"` 等のクロスプラットフォーム実コマンド |
| PID detection         | 実プロセスを spawn して PID 取得・終了確認                                      |
| OSC over UDP          | `pythonosc.osc_server.BlockingOSCUDPServer` を loopback に立てる                |
| X11 / window          | `xvfbwrapper` / `PyVirtualDisplay` で headless real X (Linux CI 可)             |
| PipeWire / PulseAudio | `pipewire` + `module-null-sink` を fixture で spawn (Linux のみ)                |
| OCR / detect          | 実 PNG fixture を実 RapidOCR / 実 OpenCV に通す。snapshot 検証                  |
| ffmpeg / muxer        | tempfile に実 ffmpeg / 実 PyAV で書き出して再 demux 検証                        |
| Windows               | GitHub Actions Windows runner + 実 Win32 API + 既知形の stub window (tkinter)   |

infra (Xvfb / PipeWire daemon spawn 等) が未整備の場合、テストは書かず
orchestrator に「integration-real が必要だが infra 未整備」と報告する。

### スキップ階層 — ファイル先頭の module-level skip

プラットフォームやディスプレイに依存するテストは **import より前** に
`pytest.skip(..., allow_module_level=True)` を置く:

```python
# 例: tests/vrcpilot/test_linux.py
import sys

import pytest

if sys.platform != "linux":
    pytest.skip("Linux-only module", allow_module_level=True)

from tests.helpers import has_x11_display  # noqa: E402

if not has_x11_display():
    pytest.skip("X11 display unavailable", allow_module_level=True)

# 以降で本物の Xlib を import して使う
```

関数単位の `@pytest.mark.skipif` だけだと、Linux runner で
`import win32gui` のような import 自体が失敗して収集エラーになる。

### `sys.platform` の monkeypatch 禁止

偽のクロスプラットフォーム保証になる。代わりに `tests/helpers.py` の
`only_windows` / `only_linux` / `requires_x11_display` を使うか、ファイル
分割 + module-level skip にする。

> NOTE: 既存 memory [feedback_test_strategy.md](../../../memory/feedback_test_strategy.md)
> は旧方針 (3rd-party 表面 fake = OK) を記述している。新方針との不整合
> がある場合は本 skill が優先。memory 側は別タスクで更新予定。

## tests/fakes/ の運用 — **縮小方向**

- `tests/fakes/` は **自前 ABC の fake のみ**残す: `FakeCapture` /
  `FakeCaptureLoop` / `FakeOCREngine` / `FakeMic` / `FakeSpeaker` /
  `FakeSpeakerLoop` 等
- **新規追加禁止のカテゴリ**: 3rd-party ライブラリ表面のミラー
  - `FakePulse*` (pulsectl), `FakeSoundCard*` (soundcard),
    `FakeWindowsCapture` (windows_capture), `FakeXDisplay*` /
    `FakePixmap*` (Xlib), `FakePopen` / `FakeProcess` (subprocess /
    psutil), `FakeProcessAudioCapture` / `FakePwRecordProcess` (proctap /
    pw-record), `FakePyDirectInput` / `FakeInputtino*` (input libs),
    `FakeMkv*` / `FakeMp4*` / `FakeWav*` Muxer (ffmpeg / PyAV)
- これらの既存 fake は整理対象だが、整理作業自体は本 skill のスコープ外
  (別タスクで対応)
- 表面拡張が必要に出ても、テストファイル内でサブクラス化せず正典クラス側
  に追加する
- 共有 fake は `tests/fakes/{audio,capture,...}.py` に集約し、テスト側は
  `from tests.fakes import FakeFoo` で import

## 何をテストするか / しないか

### 書く

- 正常系: 期待通りの入力に対する出力
- 異常系: エラー発生時の例外やメッセージ（**substring** 検証、完全一致は不可）
- 警告: 設定失敗時などの `RuntimeWarning`
- エッジケース: 境界値・空入力・巨大入力

### 書かない (marginal value ゼロ — 削除対象)

- **継承の追試**: `assert issubclass(MyError, RuntimeError)` を
  `class MyError(RuntimeError):` のために書く。pyright と Python 言語仕様
  が既に保証している
- **import 可能性の追試**: `assert X is not None` を import 直後に書く
- **定数 literal の追試**: `assert TIMEOUT == 5`。意味的不変条件
  (例: `assert TIMEOUT >= MIN_RTT`) なら OK
- **getter/setter のラウンドトリップ**: `obj.foo = x; assert obj.foo == x`
- **`__init__` でフィールド設定されたことだけの確認**
- **framework / stdlib の動作追試**: `assert json.loads("{}") == {}`
- **例外メッセージの完全一致**: `assert str(err) == "exact text"`。
  `"keyword" in str(err)` の意味性検証に留める
- **モックの戻り値をそのまま検証するだけ**: モックの動作確認になっている

### 例外: 公開 API 契約ピン

外部利用者が依存する公開 API 名・基底クラス・型エイリアスは契約として
固定する価値あり (Hyrum's law mitigation)。**唯一の例外**として:

- 集約場所: `tests/vrcpilot/test_api_contract.py`
- マーカー: `@pytest.mark.api_contract` (要 `pyproject.toml` 登録)
- 意図を明示: コメントで「これは契約ピンであり振る舞いテストではない」と書く
- 対象例: `vrcpilot.__all__` の整合性、公開例外の継承関係、公開型エイリ
  アスの解決先

## モック (使用する場合)

- `pytest_mock` を使用する（`unittest.mock` は使わない。`mocker.Mock` を使う）
- 複数のテストで共有するモックは `tests/conftest.py` にフィクスチャとして定義
- 特定のテストでのみモックの振る舞いを変更する場合、フィクスチャの戻り値で
  上書き
- **モック対象は自前 ABC のみ**。3rd-party 表面 / 自分のコードの内部関数は
  モックしない（前述）

## end-to-end シナリオ (`tests/e2e/`)

実 VRChat を起動して end-to-end で振る舞いを確認するスクリプト群。
`pytest --ignore=tests/e2e` で自動収集対象外。`just e2e-test <NAME>` で実行する。

- 各シナリオは `_helpers.run_scenario(name, body)` でラップし、`PASS:` /
  `FAIL:` の 1 行で成否を出す
- 起動 → `_helpers.warmup()` で安定待ち → 検証 → `_helpers.run_scenario`
  側が pre / post で VRChat を terminate
- 状態を変える対称 API（focus/unfocus、show/hide 等）を検証する場合は、
  起動直後の自然な状態から本命操作を呼んでも no-op と区別できないため、
  **逆操作 → 本操作 → 逆 → 本** の 4 step で書く。同じペアを 2 回繰り返す
  ことで idempotence も確認できる。`tests/e2e/focus_unfocus.py` がこの
  パターンの例
- スクリーンショットを残す場合は
  `_helpers.save_monitor_screenshot(scenario, label)` を使い、
  `_e2e_artifacts/<scenario>/<YYYYMMDD_HHMMSS>/<label>.png`（gitignore 済み）
  に PNG が保存される。Claude Code はその PNG を Read で開いて目視確認できる

Claude 自身が e2e を流す運用は [memory/feedback_e2e_run.md](../../../memory/feedback_e2e_run.md) を参照。

## pytest 設定の含意

`pyproject.toml` で `addopts = ["--strict-markers", "--doctest-modules", ...]`
が設定されている。コードを書く際の含意:

- `--doctest-modules` により `testpaths = "tests/"` 配下および import される
  source の全モジュールから doctest が収集される。docstring 内の `>>>` 例は
  実行されるため、確実にパスするよう書くか、プロンプトを省くこと
- `--strict-markers` のため、`@pytest.mark.<name>` は事前に `pyproject.toml`
  の `[tool.pytest.ini_options] markers` に登録する必要がある。未登録だと
  テストはエラーになる
- 新マーカー候補: `api_contract` (公開 API 契約ピン)、`integration_real`
  (実 resource 必須の統合テスト)

`asyncio_default_fixture_loop_scope = "function"` は `pytest-asyncio` 想定で
設定されているが、当該プラグインは現状 `dev` deps に含まれていない。async
テストを書く前に追加すること。

## 推奨ツール: mutation testing

「fake が drift しているか」を **経験的に** 検証する手段として `mutmut`
([github.com/boxed/mutmut](https://github.com/boxed/mutmut)) が有効。

- 仕組み: `mutmut` は source を機械的に corrupt し (`+` → `-`, `>` →
  `>=`, `True` → `False` 等)、テストが mutant を検出するか測る。**survive
  した mutant** は、その箇所のテストが弱い（しばしば fake が mutant を
  吸収している）合図
- CI 必須ではない。リリース前 / 四半期程度の頻度で十分
- 100% mutation score を狙わない。コストが super-linear
- 用途は弱いテストの削除と強いテストの追加判断。target metric にしない
- 適用優先: 純粋ロジック (OCR 後処理、OSC 符号化、geometry) → adapter 層

## 実行環境の注意点

### Windows 日本語環境（cp932）の非 ASCII 出力

開発環境（Windows + 日本語ロケール）では Python の `print` がデフォルトで
`cp932` (Shift-JIS) で encode される。`—`（em-dash、U+2014）など cp932 範囲外
の文字を含む文字列を `print` すると `UnicodeEncodeError` で実行時に落ちる。

- stdout に出力されうる文字列（`print` / `_helpers.log` / `assert` のメッセージ）
  は ASCII で代替する: `—` → `-`、`→` → `->`、`…` → `...`
- docstring / コメント / 日本語本文の cp932 範囲文字は問題ない
- pre-commit や pyright では検出できない（実機 print で初めて死ぬ）。
  `tests/e2e/` のシナリオで実機実行して気付くタイプの罠

### Linux で SSH 越しに e2e シナリオを動かす

同一ユーザーでローカルにデスクトップセッション（X11）が出ている前提なら、
SSH からでも `just e2e-test <NAME>` でそのデスクトップに VRChat を出して
検証できる。`justfile` は `set dotenv-load := true` を有効化済みで、
`.env`（gitignore 済み・`.env.example` をコピーして作る）から `DISPLAY` /
`XAUTHORITY` を読む。`.env` も既存のシェル env も無い場合は、`e2e-test`
レシピが `DISPLAY` 未設定時に `:0` / `~/.Xauthority` にフォールバックする。
Wayland セッションの場合はこの fallback では繋がらないので、明示的に
`WAYLAND_DISPLAY` を渡すこと。

- **Steam を先に起動しておく**: `vrcpilot.launch()` は Steam が落ちている
  状態だと裏で Steam 本体の起動から始まり、`_helpers.wait_for_pid` の 30 秒
  タイムアウトを超えて `VRChat PID was not observed before timeout` で落ちる。
  SSH から e2e を流す前にデスクトップ側で Steam を起動して常駐させておく
- 画面ロック中は window 操作系（`focus_unfocus` 等）の挙動が安定しないので、
  検証中は lock を外しておく

## 参考文献

本方針の根拠となった主要文献:

- [Martin Fowler: On the Diverse And Fantastical Shapes of Testing (2021)](https://martinfowler.com/articles/2021-test-shapes.html) — pyramid / honeycomb / trophy の整理、sociable vs solitary
- [Kent C. Dodds: Write tests. Not too many. Mostly integration.](https://kentcdodds.com/blog/write-tests) — testing trophy
- [André Schaffer (Spotify): Testing of Microservices](https://engineering.atspotify.com/2018/01/testing-of-microservices) — honeycomb shape
- [Sebastian Bergmann: Do not mock what you do not own](https://thephp.cc/articles/do-not-mock-what-you-do-not-own) — GOOS 原則
- [James Shore: Testing Without Mocks: A Pattern Language](https://www.jamesshore.com/v2/projects/nullables/testing-without-mocks) — Infrastructure Wrapper + Narrow Integration Test
- [Kent Beck: Test Desiderata](https://testdesiderata.com/) — Predictive vs Fast の trade-off
- [Hillel Wayne: Some tests are stronger than others](https://buttondown.com/hillelwayne/archive/some-tests-are-stronger-than-others/) — marginal value の見方
- [Hillel Wayne: In Defense of Testing Mocks](https://buttondown.com/hillelwayne/archive/in-defense-of-testing-mocks/) — mock を併用する条件
- [Mark Seemann: Test trivial code](https://blog.ploeh.dk/2013/03/08/test-trivial-code/) — 公開 API 契約ピンの根拠 (反対意見も含めて)
- [Martin Fowler: Test Coverage](https://martinfowler.com/bliki/TestCoverage.html) — 100% は赤信号
- [pywinauto unit-testing status](https://github.com/pywinauto/pywinauto/wiki/Unit-testing-status) — desktop-automation の前例
- [python-osc test_udp_client.py](https://github.com/attwad/python-osc/blob/main/pythonosc/test/test_udp_client.py) — loopback UDP 検証の実例
- [PipeWire null-sink module](https://docs.pipewire.org/page_pulse_module_null_sink.html) — headless audio のための null-sink
