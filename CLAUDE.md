# CLAUDE.md

このファイルは Claude Code (claude.ai/code) がこのリポジトリを扱う際のガイダンスを提供する。

## プロジェクト概要

`vrcpilot` は VRChat の操作を自動化するための Python ライブラリ。VRChat クライアントの UI 操作からゲーム内操作までを対象とする。

## メモリ参照

プロジェクト固有の規約・知見・ユーザーの好みは repo ルート [memory/](memory/) に保存する（git 管理対象）。エージェント固有メモリは [memory/agents/](memory/agents/) 配下に同じレイアウトで配置する。harness が自動ロードする `~/.claude/projects/.../memory/` パスは **使わない**（プロジェクト内の git 管理を優先する方針）。

セッション開始時、または規約が関係しそうなタスクに着手する前に [memory/MEMORY.md](memory/MEMORY.md) のインデックスを確認すること。新しい規約・フィードバック・ユーザー像が判明した場合は同ディレクトリにファイルを足し、`MEMORY.md` から 1 行リンクを張る。

## プロジェクト状況

`vrcpilot` パッケージは以下のサブシステムから構成される:

- **プロセス制御**: `process`（起動/終了/PID 検出）、`steam`（Steam 検出）、`session`（Wayland-native 判定）
- **ウィンドウ操作**: `window/`（Win32/X11 バックエンドの focus/unfocus/is_foreground）、`geometry`（ウィンドウ矩形取得）
- **キャプチャ系**: `capture/`（`Capture` + `CaptureLoop`、Win32/X11 バックエンド）、`screenshot`（GUI 自動化向けの 1 ショット取得。`Screenshot.save/load` は file-path / inline base64 の 2 モード対応で YAML を双方向にやり取り可能）
- **OCR**: `ocr/`（`OCREngine` ABC + `RapidOCREngine` 実装、`ocr()` で `Screenshot` を入力に取る、`visualize.render` で bbox 重ね描き PNG を生成）
- **画像検出**: `detect/`（`DetectEngine` ABC + `TemplateDetectEngine`（OpenCV `TM_CCOEFF_NORMED`）実装、`detect()` で `Screenshot` + クエリ画像から座標付き `Detection` 列を返す、`visualize.render` で OCR と同一スキーマの可視化）
- **入力制御**: `controls/`（VRChat フォーカス保証つきの `keyboard` / `mouse`、`guard`、`errors`）、`clipboard`（pyperclip + Ctrl+V で scancode keyboard の非 ASCII 制限を回避）
- **OSC**: `osc/`（`OscSender` 低レベル送信、`OscController` ボタン / 軸 / typing / chatbox、`OscAvatar` パラメータ送信。CLI 側は `cli/osc.py` で `send` / `axis` / `tap` / `hold` / `chatbox` / `typing` / `avatar` の 7 アクション）
- **音声系 (出力キャプチャ)**: `speaker/`（`Speaker` + `SpeakerLoop`。Linux はネイティブ PipeWire パイプライン（`pw-link` + `pw-record` + `pulsectl` 制御平面）、Windows / macOS は `proc-tap` プロセスループバックで、いずれも VRChat.exe からのみ音声を抽出する Python API。Windows / Linux は stable、macOS は experimental）
- **音声系 (仮想マイク入力)**: `mic/`（`Mic` を `soundcard` バックエンドで開き、Windows は VB-Audio Virtual Cable、Linux は `mic/linux.py` 経由で PipeWire `VRCPilotMic` 仮想 sink を登録・管理。Linux 限定の `linux.py` を持つ）
- **CLI フロントエンド**: `cli/` 配下にサブコマンド毎 1 ファイル（`launch` / `pid` / `terminate` / `focus` / `unfocus` / `screenshot` / `record` / `mouse` / `keyboard` / `paste` / `ocr` / `detect` / `osc` / `mic` / `linux-mic`）、ディスパッチは `cli/__init__.py` の `build_parser` / `main`、共有ヘルパは `cli/_common.py`（`add_screenshot_input_arg` / `resolve_screenshot` で `--screenshot` ↔ stdin pipe の入力解決を集約）

プラットフォーム抽象は親 `__init__.py` で `sys.platform` ディスパッチして公開する（`__all__` 経由で公開 API を集約）。プラットフォーム固有の低レベル実装（`steam`, `win32`, `x11`, `capture/{win32,x11}`, `window/{win32,x11}`, `controls/{keyboard,mouse}`, `speaker/{pipewire,proctap}`）は対応モジュールに配置している。`speaker/` は `session.py` から Linux 用 `pipewire.py` と Windows / macOS 用 `proctap.py` を `sys.platform` でディスパッチする。`mic/` は `soundcard` 側で OS 抽象が完結するが、PipeWire 仮想 sink 管理だけは Linux 限定の `mic/linux.py` に切り出している。

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

## CLI / テスト方針の詳細リファレンス

常時ロードを避けるため `.claude/skills/` 配下にオフロードしてある。必要な
ときに skill を呼び出すか、根拠となる shared memory を直接参照する:

- **CLI 詳細**: `/vrcpilot-cli` skill — `uv run vrcpilot ...` のサブコマンド
  表、`screenshot → ocr / detect` の標準パイプライン、`osc` 7 アクションの
  典型例、OCR / detect の座標系（`pos` = window-local）
- **テスト方針**: `/vrcpilot-testing` skill — 4 区分のテスト戦略、tests
  ミラーレイアウト、共有 fakes、`pytest --doctest-modules` /
  `--strict-markers` の含意、`tests/e2e/` シナリオ作法、Windows cp932 /
  Linux SSH e2e の実行環境クセ
- **VRChat 実機 end-to-end 手順**: [memory/feedback_vrchat_cli_playbook.md](memory/feedback_vrchat_cli_playbook.md)

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

詳細: [memory/feedback_private_module_convention.md](memory/feedback_private_module_convention.md)

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
