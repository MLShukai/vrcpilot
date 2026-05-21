---
name: vrcpilot-testing
description: vrcpilot のテスト方針詳細。4 区分のテスト戦略（unit / integration-with-fakes / integration-real / e2e）、tests ミラーレイアウト、共有 fakes、pytest --doctest-modules / --strict-markers の含意、Windows cp932 と Linux SSH e2e の実行環境クセ。テストコードを書く／壊れた e2e を調査する／pytest 周りを設定する前に読む
---

# vrcpilot テスト方針リファレンス

詳細な学び（4 区分の分類根拠など）は memory ファイル群に集約されている。本
skill は手元で書き始める前にざっと読む「実行可能なまとめ」として位置づける。

## 基本原則

- 必要十分なテストのみを記述する。過剰なテストは避ける
- 内部実装の詳細はテストしない。公開インターフェースと振る舞いをテストする
- テスト関数に戻り値の型アノテーションは不要

## テストレイアウト

`tests/` は `src/vrcpilot/` の構造を 1 対 1 でミラーリングする:

- `src/vrcpilot/foo.py` ↔ `tests/vrcpilot/test_foo.py`
- `src/vrcpilot/__init__.py` ↔ `tests/vrcpilot/test_init.py`
- `src/vrcpilot/sub/bar.py` ↔ `tests/vrcpilot/sub/test_bar.py`
- `tests/` 直下に置くのは `__init__.py` / `helpers.py` / `conftest.py` / `manual/` のみ
- 1 ファイル 1 テストを原則とし、`window/{win32,x11}.py` のようにバックエンド
  分割されているソースはテストも分けて 1 対 1 を維持する

詳細: [memory/feedback_test_layout_mirror.md](../../../memory/feedback_test_layout_mirror.md)

## 実践的なテスト

- 実際のオブジェクトを生成し、実際の入出力で振る舞いを検証する
- できる限りモックを使わない。外部依存であっても、テスト用の実データ（一時
  ファイル等）を生成して回避できる場合は実データを使う
- モックは最小限にとどめる。モックを使ってよいのは以下の場合のみ:
  - 外部 API（VRChat API などネットワーク通信を伴うもの）
  - ファイルシステムや DB など、テスト環境で再現が困難な外部依存
- 内部モジュール同士の結合はモックせず、実際に結合してテストする
- 複数のパラメータをテストする場合は `@pytest.mark.parametrize` を使用する
- ABC のみで具象クラスが存在しない場合、テスト用のシンプルな Impl 具象クラス
  を `tests/helpers.py` に定義する（モックは使わない）

## モック（使用する場合）

- `pytest_mock` を使用する（unittest の mock は使わない。`mocker.Mock` を使う）
- 複数のテストで共有するモックは `tests/conftest.py` にフィクスチャとして定義する
- 特定のテストでのみモックの振る舞いを変更する場合、フィクスチャの戻り値を
  使って設定を上書きする

## テスト区分とスキップ階層

テストは 4 区分（unit / integration-with-fakes / integration-real / manual e2e）
で組み立てる。区分が決まれば配置・モック許容度・スキップ方法が一意に決まる。
詳細は [memory/feedback_test_strategy.md](../../../memory/feedback_test_strategy.md)。

- **共有 fake は `tests/fakes/`**: `FakeWindowsCapture` / `FakeCaptureLoop` /
  `FakeMp4Sink` / `FakeProcess` / `FakePopen` / `FakeXDisplay` などをここに
  集約。テスト側は `from tests.fakes import FakeFoo` で import する。テスト
  ファイル内でアドホックに `class _Fake*` を定義しない
- **module-level skip**: プラットフォームやディスプレイに依存して **import
  自体が失敗しうる** テストは、ファイル先頭で
  `if <condition>: pytest.skip(reason, allow_module_level=True)` を **import
  文より前** に置く。関数単位の `@pytest.mark.skipif` だけでは収集エラーを
  防げない
- **`sys.platform` の monkeypatch は禁止**: 偽のクロスプラットフォーム保証に
  なる。代わりに `tests/helpers.py` の `only_windows` / `only_linux` /
  `requires_x11_display` を使うか、ファイル分割 + module-level skip にする

## 何をテストするか / しないか

書く:

- 正常系: 期待通りの入力に対する出力
- 異常系: エラー発生時の例外やメッセージ
- 警告: 設定失敗時などの `RuntimeWarning`
- エッジケース: 境界値やサイズ違いの入力

書かない:

- 内部実装の詳細（例: 特定のメソッドが呼ばれたか）
- 初期化時のプロパティ設定などの内部動作

## end-to-end シナリオ（`tests/e2e/`）

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
  `_e2e_artifacts/`（gitignore 済み）に PNG が保存される。Claude Code は
  その PNG を Read で開いて目視確認できる

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

`asyncio_default_fixture_loop_scope = "function"` は `pytest-asyncio` 想定で
設定されているが、当該プラグインは現状 `dev` deps に含まれていない。async
テストを書く前に追加すること。

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
