# CLAUDE.md

このファイルは Claude Code (claude.ai/code) がこのリポジトリを扱う際のガイダンスを提供する。

## プロジェクト概要

`vrcpilot` は VRChat の操作を自動化するための Python ライブラリ。VRChat クライアントの UI 操作からゲーム内操作までを対象とする。

## メモリ参照

プロジェクト固有の規約・知見・ユーザーの好みは `.claude/memory/` に保存する（git 管理対象、subagent 用の `.claude/agent-memory/` と同じ階層）。harness が自動ロードする `~/.claude/projects/.../memory/` パスは **使わない**（プロジェクト内の git 管理を優先する方針）。

セッション開始時、または規約が関係しそうなタスクに着手する前に [.claude/memory/MEMORY.md](.claude/memory/MEMORY.md) のインデックスを確認すること。新しい規約・フィードバック・ユーザー像が判明した場合は同ディレクトリにファイルを足し、`MEMORY.md` から 1 行リンクを張る。

## プロジェクト状況

`vrcpilot` パッケージは以下のサブシステムから構成される:

- **プロセス制御**: `process`（起動/終了/PID 検出）、`steam`（Steam 検出）、`session`（Wayland-native 判定）
- **ウィンドウ操作**: `window/`（Win32/X11 バックエンドの focus/unfocus/is_foreground）、`geometry`（ウィンドウ矩形取得）
- **キャプチャ系**: `capture/`（`Capture` + `CaptureLoop` + `Mp4FrameSink` / `Y4mStdoutFrameSink`、Win32/X11 バックエンド）、`screenshot`（GUI 自動化向けの 1 ショット取得。`Screenshot.save/load` は file-path / inline base64 の 2 モード対応で YAML を双方向にやり取り可能）
- **OCR**: `ocr/`（`OCREngine` ABC + `RapidOCREngine` 実装、`ocr()` で `Screenshot` を入力に取る、`visualize.render` で bbox 重ね描き PNG を生成）
- **画像検出**: `detect/`（`DetectEngine` ABC + `TemplateDetectEngine`（OpenCV `TM_CCOEFF_NORMED`）実装、`detect()` で `Screenshot` + クエリ画像から座標付き `Detection` 列を返す、`visualize.render` で OCR と同一スキーマの可視化）
- **入力制御**: `controls/`（VRChat フォーカス保証つきの `keyboard` / `mouse`、`guard`、`errors`）、`clipboard`（pyperclip + Ctrl+V で scancode keyboard の非 ASCII 制限を回避）
- **CLI フロントエンド**: `cli/` 配下にサブコマンド毎 1 ファイル（`launch` / `pid` / `terminate` / `focus` / `unfocus` / `screenshot` / `capture` / `mouse` / `keyboard` / `paste` / `ocr` / `detect`）、ディスパッチは `cli/__init__.py` の `build_parser` / `main`、共有ヘルパは `cli/_common.py`（`add_screenshot_input_arg` / `resolve_screenshot` で `--screenshot` ↔ stdin pipe の入力解決を集約）

プラットフォーム抽象は親 `__init__.py` で `sys.platform` ディスパッチして公開する（`__all__` 経由で公開 API を集約）。プラットフォーム固有の低レベル実装（`steam`, `win32`, `x11`, `capture/{win32,x11,sinks}`, `window/{win32,x11}`, `controls/{keyboard,mouse}`）は対応モジュールに配置している。

## ツーリング

- パッケージ・環境管理: `uv`（ロックファイル `uv.lock` をコミット済み）
- Python: `>=3.12` 必須。CI は Linux / Windows × 3.12 / 3.13 / 3.14 のマトリクス
- タスクランナー: `just`（`justfile`）。Windows でも `just` は Git Bash を呼び出す設定なのでレシピは Unix シェル前提で書く
- 型チェッカー: `pyright` を `./src/` に対し **strict** モードで実行（`tests/` は除外）。`reportImplicitOverride` 有効、`reportPrivateUsage` は警告
- リンター/フォーマッター: `ruff`（line-length 88、ダブルクォート、isort + `combine-as-imports`）
- pre-commit: ruff、pyupgrade（`--py312-plus`）、docformatter、mdformat、codespell、`uv-lock`（lockfile 鮮度）、pygrep checks（`python-check-blanket-noqa`、`python-no-log-warn` 等）を実行

## コマンド

`just` レシピを使う（`uv run` をラップしているので venv が常に尊重される）:

- `just setup` - 開発環境のセットアップ（`uv venv` + `uv sync --all-extras` + `pre-commit install`）
- `just format` - pre-commit フックを実行（ruff fix + format、mdformat、codespell など）
- `just test` - `uv run pytest -v --cov`
- `just type` - `uv run pyright`
- `just run` - format → test → type を順に実行
- `just clean` - `dist/`、`__pycache__`、`.pytest_cache`、`.coverage` 等を削除

細かい制御が必要な場合の直接呼び出し:

- 単一テスト: `uv run pytest tests/vrcpilot/test_init.py::TestPackage::test_version -v`
- キーワードフィルタ: `uv run pytest -v -k "<expr>"`
- 単一パスへの pyright: `uv run pyright src/vrcpilot/<file>.py`
- 単一の pre-commit フック: `uv run pre-commit run ruff -a`

## CLI（`vrcpilot` / `python -m vrcpilot`）の使い方

VRChat を実機で操作する end-to-end な手順は [.claude/memory/feedback_vrchat_cli_playbook.md](.claude/memory/feedback_vrchat_cli_playbook.md)。ここでは Claude が CLI 経由で何を呼ぶかを概観する。

### サブコマンド一覧

すべて `uv run vrcpilot <subcommand> ...` で起動する（PEP 723 の console-script `vrcpilot` 経由）。詳細は `--help` または各 `cli/<name>.py` の docstring。

| サブコマンド | 用途                                                                                                   | 状態系の出力                                                                                 |
| ------------ | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| `launch`     | Steam 経由で VRChat を起動。`--no-vr` / `--screen-{width,height}` / `--osc-in-port` / `--wait-timeout` | stdout に PID（待機完了時）、`--wait-timeout 0` で即時 return                                |
| `pid`        | 動作中 VRChat の PID 一覧                                                                              | 1 行 1 PID。誰もいなければ exit 1                                                            |
| `terminate`  | VRChat を強制終了（idempotent）                                                                        | 殺した PID のみ stdout、対象なしは無音で exit 0                                              |
| `focus`      | VRChat ウィンドウを前面に                                                                              | 成功は無音、失敗は stderr 1 行                                                               |
| `unfocus`    | VRChat ウィンドウを z-order 末尾に                                                                     | 同上                                                                                         |
| `screenshot` | 1 枚撮って `Screenshot` を YAML で吐く                                                                 | `-o <path>` で PNG を書き出し YAML に `path:` を、未指定で base64 PNG を埋め込む（`image:`） |
| `capture`    | 一定 FPS で録画                                                                                        | `-o <path>` で mp4、未指定で y4m を stdout（TTY なら拒否）                                   |
| `mouse`      | `move` / `click` / `scroll`（`press`/`release` は意図的に未公開）                                      | guard 失敗で exit 1                                                                          |
| `keyboard`   | `press` のみ公開（`down` / `up` をプロセスに跨いで持てないため）                                       | `--duration` のデフォルト 0.1（VRChat に届く下限。0.0 にしない）                             |
| `paste`      | クリップボード経由で文字列を Ctrl+V 投入（非 ASCII 用）                                                | 引数 or stdin から読む。tty かつ引数なしは exit 2                                            |
| `ocr`        | `Screenshot` を入力に RapidOCR を回し、認識単語を YAML で返す                                          | `--viz` で bbox 重ね PNG。**`--screenshot` か stdin pipe が必須**                            |
| `detect`     | `Screenshot` 内をクエリ画像でテンプレート検索                                                          | `-q <png>` 必須。`--threshold` / `--top-k` / `--viz`。同じく入力 YAML 必須                   |
| `osc`        | VRChat OSC 送信 (`send` / `axis` / `tap` / `hold` / `chatbox` / `typing` / `avatar` の 7 アクション)   | 成功は無音。range/name 違反で exit 1、`chatbox` は tty かつ引数なしで exit 2                 |

### 標準パイプライン（重要）

`vrcpilot ocr` と `vrcpilot detect` は **自身でスクリーンショットを撮らない**（過去にあった live capture は `feat(cli)!: ocr/detect の自動 live capture 経路を廃止` で削除）。`vrcpilot screenshot` の出力 YAML を pipe するか、`--screenshot <yaml>` で渡すこと。

```bash
# ① インライン base64 を pipe（一番短い形）
uv run vrcpilot screenshot | uv run vrcpilot ocr --viz /tmp/viz.png > /tmp/ocr.yaml

# ② PNG を残しつつ pipe（後で目視確認したいとき）
uv run vrcpilot screenshot -o /tmp/shot.png | uv run vrcpilot ocr > /tmp/ocr.yaml

# ③ 既存の YAML を再利用
uv run vrcpilot screenshot -o /tmp/shot.png > /tmp/shot.yaml
uv run vrcpilot detect -q ./assets/button.png --screenshot /tmp/shot.yaml > /tmp/det.yaml
```

`vrcpilot screenshot` 単体も挙動が 2 系統ある:

- `-o <path>` あり: PNG を書き出し、YAML には `path:` で絶対パスを記録（履歴を残す pipeline 向け）
- `-o` なし（デフォルト）: PNG ファイルは作らず、YAML 内 `image:` に base64 PNG を埋め込む（pipe で消費する想定）

### OSC コマンドの典型例

`vrcpilot osc` は VRChat の OSC API を CLI から叩くための入口。接続パラメータ (`--host` / `--port` / `--button-hold`) は親 `osc` の直後に書き、アクションはその後ろに置く (`vrcpilot osc --host 192.168.1.10 tap jump` の順)。送信専用で listen 系は未提供、`OscSender.send` の任意 Python 値パススルーは Python API 側のエスケープハッチに留めて CLI 非公開（`send` サブアクションは `--bool` / `--int` / `--float` の必須 mutex で型を明示する）。

```bash
# 入力コントローラ系: tap (1 → sleep --button-hold → 0)
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

# 送信先を変える (例: 異なるホスト/ポートに転送)
uv run vrcpilot osc --host 192.168.1.10 --port 9100 tap jump

# 低レベル escape hatch (任意 OSC アドレスへ型付き送信)
uv run vrcpilot osc send /custom/Address --int 42
```

### 座標系

OCR / detect の YAML は同じ座標スキーマで揃えてある:

- `pos.{polygon,bbox}`: ウィンドウローカル（左上 origin）
- `display_pos.{polygon,bbox}`: デスクトップ絶対（`window.x` / `window.y` でシフト済み）
- `vrcpilot mouse move <x> <y>` に渡すのは **必ず `display_pos.bbox`**。`pos` をそのまま渡すとマルチモニタや非原点ウィンドウで外れる

## pytest 設定の注意点

`pyproject.toml` で `addopts = ["--strict-markers", "--doctest-modules", ...]` が設定されている。コードを書く際の含意:

- `--doctest-modules` により `testpaths = "tests/"` 配下および import される source の全モジュールから doctest が収集される。docstring 内の `>>>` 例は実行されるため、確実にパスするよう書くか、プロンプトを省くこと
- `--strict-markers` のため、`@pytest.mark.<name>` は事前に `pyproject.toml` の `[tool.pytest.ini_options] markers` に登録する必要がある。未登録だとテストはエラーになる

`asyncio_default_fixture_loop_scope = "function"` は `pytest-asyncio` 想定で設定されているが、当該プラグインは現状 `dev` deps に含まれていない。async テストを書く前に追加すること。

## 実行環境の注意点

### Windows 日本語環境（cp932）の非 ASCII 出力

開発環境（Windows + 日本語ロケール）では Python の `print` がデフォルトで `cp932` (Shift-JIS) で encode される。`—`（em-dash, U+2014）など cp932 範囲外の文字を含む文字列を `print` すると `UnicodeEncodeError` で実行時に落ちる。

- stdout に出力されうる文字列（`print` / `_helpers.log` / `assert` のメッセージ）は ASCII で代替する: `—` → `-`、`→` → `->`、`…` → `...`
- docstring / コメント / 日本語本文の cp932 範囲文字は問題ない
- pre-commit や pyright では検出できない（実機 print で初めて死ぬ）。`tests/e2e/` のシナリオで実機実行して気付くタイプの罠

### Linux で SSH 越しに e2e シナリオを動かす

同一ユーザーでローカルにデスクトップセッション（X11）が出ている前提なら、SSH からでも `just e2e-test <NAME>` でそのデスクトップに VRChat を出して検証できる。`justfile` は `set dotenv-load := true` を有効化済みで、`.env`（gitignore 済み・`.env.example` をコピーして作る）から `DISPLAY` / `XAUTHORITY` を読む。`.env` も既存のシェル env も無い場合は、`e2e-test` レシピが `DISPLAY` 未設定時に `:0` / `~/.Xauthority` にフォールバックする。Wayland セッションの場合はこの fallback では繋がらないので、明示的に `WAYLAND_DISPLAY` を渡すこと。

- **Steam を先に起動しておく**: `vrcpilot.launch()` は Steam が落ちている状態だと裏で Steam 本体の起動から始まり、`_helpers.wait_for_pid` の 30 秒タイムアウトを超えて `VRChat PID was not observed before timeout` で落ちる。SSH から e2e を流す前にデスクトップ側で Steam を起動して常駐させておく
- 画面ロック中は window 操作系（`focus_unfocus` 等）の挙動が安定しないので、検証中は lock を外しておく

## テスト方針

### 基本原則

- 必要十分なテストのみを記述する。過剰なテストは避ける
- 内部実装の詳細はテストしない。公開インターフェースと振る舞いをテストする
- テスト関数に戻り値の型アノテーションは不要

### テストレイアウト

`tests/` は `src/vrcpilot/` の構造を 1 対 1 でミラーリングする:

- `src/vrcpilot/foo.py` ↔ `tests/vrcpilot/test_foo.py`
- `src/vrcpilot/__init__.py` ↔ `tests/vrcpilot/test_init.py`
- `src/vrcpilot/sub/bar.py` ↔ `tests/vrcpilot/sub/test_bar.py`
- `tests/` 直下に置くのは `__init__.py` / `helpers.py` / `conftest.py` / `manual/` のみ
- 1 ファイル 1 テストを原則とし、`window/{win32,x11}.py` のようにバックエンド分割されているソースはテストも分けて 1 対 1 を維持する

詳細: [.claude/memory/feedback_test_layout_mirror.md](.claude/memory/feedback_test_layout_mirror.md)

### 実践的なテスト

- 実際のオブジェクトを生成し、実際の入出力で振る舞いを検証する
- できる限りモックを使わない。外部依存であっても、テスト用の実データ（一時ファイル等）を生成して回避できる場合は実データを使う
- モックは最小限にとどめる。モックを使ってよいのは以下の場合のみ:
  - 外部 API（VRChat API などネットワーク通信を伴うもの）
  - ファイルシステムや DB など、テスト環境で再現が困難な外部依存
- 内部モジュール同士の結合はモックせず、実際に結合してテストする
- 複数のパラメータをテストする場合は `@pytest.mark.parametrize` を使用する
- ABC のみで具象クラスが存在しない場合、テスト用のシンプルな Impl 具象クラスを `tests/helpers.py` に定義する（モックは使わない）

### モック（使用する場合）

- `pytest_mock` を使用する（unittest の mock は使わない。`mocker.Mock` を使う）
- 複数のテストで共有するモックは `tests/conftest.py` にフィクスチャとして定義する
- 特定のテストでのみモックの振る舞いを変更する場合、フィクスチャの戻り値を使って設定を上書きする

### テスト区分とスキップ階層

テストは 4 区分（unit / integration-with-fakes / integration-real / manual e2e）で組み立てる。区分が決まれば配置・モック許容度・スキップ方法が一意に決まる。詳細は [.claude/memory/feedback_test_strategy.md](.claude/memory/feedback_test_strategy.md)。

- **共有 fake は `tests/fakes/`**: `FakeWindowsCapture` / `FakeCaptureLoop` / `FakeMp4Sink` / `FakeProcess` / `FakePopen` / `FakeXDisplay` などをここに集約。テスト側は `from tests.fakes import FakeFoo` で import する。テストファイル内でアドホックに `class _Fake*` を定義しない
- **module-level skip**: プラットフォームやディスプレイに依存して **import 自体が失敗しうる** テストは、ファイル先頭で `if <condition>: pytest.skip(reason, allow_module_level=True)` を **import 文より前** に置く。関数単位の `@pytest.mark.skipif` だけでは収集エラーを防げない
- **`sys.platform` の monkeypatch は禁止**: 偽のクロスプラットフォーム保証になる。代わりに `tests/helpers.py` の `only_windows` / `only_linux` / `requires_x11_display` を使うか、ファイル分割 + module-level skip にする

### 何をテストするか

- 正常系: 期待通りの入力に対する出力
- 異常系: エラー発生時の例外やメッセージ
- 警告: 設定失敗時などの `RuntimeWarning`
- エッジケース: 境界値やサイズ違いの入力

### 何をテストしないか

- 内部実装の詳細（例: 特定のメソッドが呼ばれたか）
- 初期化時のプロパティ設定などの内部動作

### end-to-end シナリオ（tests/e2e/）

実 VRChat を起動して end-to-end で振る舞いを確認するスクリプト群。`pytest --ignore=tests/e2e` で自動収集対象外。`just e2e-test <NAME>` で実行する。

- 各シナリオは `_helpers.run_scenario(name, body)` でラップし、`PASS:` / `FAIL:` の 1 行で成否を出す
- 起動 → `_helpers.warmup()` で安定待ち → 検証 → `_helpers.run_scenario` 側が pre/post で VRChat を terminate
- 状態を変える対称 API（focus/unfocus, show/hide 等）を検証する場合は、起動直後の自然な状態から本命操作を呼んでも no-op と区別できないため、**逆操作 → 本操作 → 逆 → 本** の 4 step で書く。同じペアを 2 回繰り返すことで idempotence も確認できる。`tests/e2e/focus_unfocus.py` がこのパターンの例
- スクリーンショットを残す場合は `_helpers.save_monitor_screenshot(scenario, label)` を使い、`_e2e_artifacts/`（gitignore 済み）に PNG が保存される。Claude Code はその PNG を Read で開いて目視確認できる

## コーディング規約

### ソースレイアウト

- `src/vrcpilot/`（PEP 561 typed、`py.typed` 同梱）。インポート名は `vrcpilot`（distribution 名からのアンダースコアマッピングは `__init__.py` の `metadata.version` ルックアップで処理）
- テストは `tests/` 配下に置き、pyright strict チェックからは除外されるが、ruff と pre-commit は通る
- バージョンは単一の真実: `pyproject.toml` の `[project].version` が真値で、`vrcpilot.__version__` は `importlib.metadata` 経由で読む。既存の `tests/vrcpilot/test_init.py::TestPackage::test_version` がこれを強制しているため、他の場所にバージョンをハードコードしないこと

### private モジュール規約

`src/vrcpilot/` 配下のモジュールは **テストの有無** で `_` prefix の有無を決める:

- テストを書かない（真に private な実装）→ ファイル名に `_` prefix を付ける（例: `_session.py`）
- テストを書く / 書かれている → `_` prefix を **付けない**（例: `steam.py`, `win32.py`, `x11.py`, `capture/sinks.py`）
- 外部公開は親 `__init__.py` の `__all__` で別軸として集約管理する。モジュール名から `_` を外すことと「外部公開」は独立した判断

詳細: [.claude/memory/feedback_private_module_convention.md](.claude/memory/feedback_private_module_convention.md)

### カプセル化

- クラスの内部実装の詳細や属性は、基本的にすべて private（`_` prefix）にする
- 外部から参照する必要がある属性のみ public にする
- `__init__` で設定される属性は原則として private とする

例:

```python
class Example:
    def __init__(self, dim: int):
        self._dim = dim  # private
        self._client = SomeClient(dim)  # private
```

## Git 運用

### ブランチ

- `main`: 開発の主軸
- 作業用ブランチの命名規則: `<種別>/<日付>/<内容>`
  - 例: `feature/20260427/auth-flow`、`fix/20260427/version-lookup`
  - 種別: `feature`, `fix`, `refactor`, `docs`, `chore`
- 必ずブランチ上でのみ commit する（`main` に直接 commit しない）
- 作業ブランチは `main` ブランチから分岐する
- `main` へのマージはユーザーが判断・実行する

### コミットメッセージ

`<種別>(<スコープ>): <内容>` の形式に従う。

- 種別: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- スコープ: モジュール名、機能名、ファイル等の単位
- 例: `feat(client): VRChat OAuth クライアントを追加`

## 自走開発フロー

Claude Code が自律的に実装・検証・コミットを行うためのフロー。

### 基本サイクル

1. **要件確認**: 要件定義ドキュメントがあれば読み、実装対象を把握する
2. **作業ブランチ作成**: `main` ブランチから `<種別>/<日付>/<内容>` で作業ブランチを切る
3. **実装**: コードを書く
4. **検証**: `just run`（`just format && just test && just type` 相当）を実行し、すべてパスすることを確認する
5. **コミット**: 検証が通ったらコミットする。細かい単位でコミットし、1 コミットに複数の関心事を混ぜない
6. **繰り返し**: 3-5 を機能単位で繰り返す

### 検証の原則

- **コミット前に必ず検証する**: `just run` がすべてパスすること
- テストが失敗した場合はコミットせず、修正してから再検証する
- 新しいモジュールを追加した場合はテストも書く
- 型チェックエラーを放置しない

### 判断基準

- 要件定義に明記されている内容はそのまま実装する
- 要件定義に記載がない実装の詳細（アルゴリズムの選択、内部設計等）は自分で判断してよい
- 要件定義の未決事項に関わる部分は、合理的なデフォルトで実装し、コミットメッセージに判断理由を記載する
- スコープ外の機能は実装しない

## エージェントチーム戦略

「エージェントチームで行う」という指示があり、具体的な手順が示されていない場合、以下のサイクルに従う。利用可能なエージェントは `.claude/agents/` および本リポジトリで定義されているものを使う。

### 実装サイクル

1. **spec-planner**: 要件を分析し、インターフェース設計と実装計画を策定する（コードは書かない）
2. **spec-driven-implementer → code-quality-reviewer**: 計画に基づき実装し、リファクタリングする。品質が十分になるまで繰り返す
3. **docstring-author**: 最後にコメントやドキュメントの追加・更新が必要か確認する

### 並列化

- 変更規模に応じて並列に動作するエージェント数を増やす
- 並列化の対象: spec-driven-implementer、code-quality-reviewer
- 分割可能なタスク数だけ並列に実行する（独立したモジュールや機能ごとに分割）
