# CLAUDE.md

`vrcpilot` は VRChat の操作を自動化する Python ライブラリ。VRChat クライアントの UI 操作からゲーム内操作までを対象とする。

対応プラットフォームは **Windows と Linux のみ**。それ以外では `import vrcpilot` の時点で `ImportError` を送出する (親 `__init__.py` 冒頭の `if sys.platform not in ("win32", "linux")` ガード)。`proc-tap` 依存も `pyproject.toml` で `sys_platform == 'win32'` に限定。

## サブシステム構成

`src/vrcpilot/` (PEP 561 typed、`py.typed` 同梱)。詳細は各サブパッケージの `__init__.py` docstring を読む。

| 領域         | モジュール                                                                                         |
| ------------ | -------------------------------------------------------------------------------------------------- |
| プロセス制御 | `process` (起動/終了/PID)、`steam`、`session` (Wayland-native 判定)                                |
| ウィンドウ   | `window/` (focus/unfocus/is_foreground)、`geometry` (矩形取得)                                     |
| キャプチャ   | `capture/` (`Capture` + `CaptureLoop`)、`screenshot` (1 ショット。`save`/`load` で YAML 双方向)    |
| 認識         | `ocr/` (`OCREngine` ABC + RapidOCR)、`detect/` (`DetectEngine` ABC + OpenCV テンプレートマッチ)    |
| 入力制御     | `controls/` (`keyboard` / `mouse` / `guard`。VRChat フォーカス保証つき)、`clipboard` (非 ASCII 用) |
| OSC          | `osc/` (`OscSender` / `OscController` / `OscAvatar`)                                               |
| 音声出力     | `speaker/` (VRChat.exe からのみ抽出)、`speaker/routing/` (PID-scoped リレー、cross-platform)       |
| 音声入力     | `mic/` (`soundcard` バックエンド。Win は VB-Audio、Linux は PipeWire 仮想 sink)                    |
| CLI          | `cli/` サブコマンド毎 1 ファイル。dispatch は `cli/__init__.py` の `build_parser` / `main`         |

**platform 別実装ファイルの命名規約**: 該当 platform 専用の低レベル実装は **`windows.py` / `linux.py`** で統一する (旧 `win32.py` / `x11.py` / `proctap.py` / `pipewire.py` は廃止)。各ファイルは冒頭で `if sys.platform != "<plat>": raise ImportError("<module> is <Plat>-only")` の素のガードを持ち、`TYPE_CHECKING` で platform import を回避する技法は使わない。pyright は実行 platform のみで strict が通ればよい。クラス名 (`Win32CaptureBackend`, `X11CaptureBackend`, `ProcTapSpeakerBackend`, `PipeWireSpeakerBackend` 等) はファイル名のリネームとは独立に保持。dispatch は親 `__init__.py` / `session.py` で `sys.platform` チェック後に lazy import する。

## ツーリングとコマンド

`uv` 管理 (`uv.lock` コミット済み)、Python `>=3.12`、CI は Linux / Windows × 3.12 / 3.13 / 3.14。型チェックは `pyright` strict (`src/` のみ、`tests/` は除外)。lint / format は `ruff` (line-length 88、ダブルクォート) と pre-commit に集約する。

`just` レシピを使う (`uv run` をラップするので venv が常に尊重される)。Windows でも `just` は Git Bash を呼ぶのでレシピは Unix シェル前提:

- `just setup` — 環境構築
- `just run` — **コミット前のゲート**。format (pre-commit 全 hook) → test → type
- `just e2e-test <NAME>` — `tests/e2e/<NAME>.py` を実 VRChat に対して実行 (省略時は all)
- 個別: `just format` / `just test` / `just type` / `just clean`

細かい制御が必要なときは直接呼ぶ: `uv run pytest -v -k "<expr>"`、`uv run pyright src/vrcpilot/<file>.py`、`uv run pre-commit run <hook> -a`。

## コーディング規約

### private モジュール規約

`src/vrcpilot/` のモジュールは **テストの有無** で `_` prefix を決める。テストを書かない真に private な実装は `_session.py` のように prefix を付け、テストを書く / 書かれているものは付けない (`steam.py`, `windows.py`, `capture/sinks.py`)。外部公開は親 `__init__.py` の `__all__` で別軸として管理する — モジュール名から `_` を外すことと「外部公開」は独立した判断。詳細: [memory/feedback_private_module_convention.md](memory/feedback_private_module_convention.md)

### import スタイル

同じサブパッケージ内は相対 import、サブパッケージ境界を跨ぐなら絶対 import。迷ったら絶対。詳細: [memory/feedback_import_style.md](memory/feedback_import_style.md)

### カプセル化

クラスの内部実装の詳細・属性は原則すべて private (`_` prefix) にし、外部から参照する必要があるものだけ public にする。`__init__` で設定される属性は原則 private。

### バージョンは単一の真実

`pyproject.toml` の `[project].version` が真値で、`vrcpilot.__version__` は `importlib.metadata` 経由で読む。`tests/vrcpilot/test_init.py::TestPackage::test_version` がこれを強制しているので、他の場所にバージョンをハードコードしない。

### テスト

`tests/` は `src/vrcpilot/` を 1 対 1 でミラーする。real-resource を最優先し、自前 ABC のみ fake 可、3rd-party ライブラリ表面のモックは禁止。書き始める前に [vrcpilot-testing](.claude/skills/vrcpilot-testing/SKILL.md) を読む。

## メモリ参照

プロジェクト固有の規約・知見・ユーザーの好みは repo ルートの [memory/](memory/) に保存する (git 管理対象)。エージェント固有メモリは [memory/agents/](memory/agents/) 配下に同じレイアウトで置く。**harness が自動ロードする `~/.claude/projects/.../memory/` と gitignore 済みの `.claude/agent-memory/` は使わない** — プロジェクト内 git 管理を優先する方針。

セッション開始時、または規約が関係しそうなタスクに着手する前に [memory/MEMORY.md](memory/MEMORY.md) のインデックスを確認する。新しい規約・知見が判明したら同ディレクトリにファイルを足し、`MEMORY.md` から 1 行リンクを張る。

## skill 索引

常時ロードを避けるため、詳細な手順は `.claude/skills/` にオフロードしてある。着手前に該当する skill を呼ぶ:

| 状況                                                   | skill                                                            |
| ------------------------------------------------------ | ---------------------------------------------------------------- |
| tracked file を変更する / commit する / ブランチを切る | [git-ops](.claude/skills/git-ops/SKILL.md)                       |
| PR を出す / CI 結果を見る / issue を操作する           | [github-pr](.claude/skills/github-pr/SKILL.md)                   |
| main を取り込む / コンフリクトを解消する               | [merge-main](.claude/skills/merge-main/SKILL.md)                 |
| 本流を汚さず別ブランチで隔離実行する                   | [do-on-worktree](.claude/skills/do-on-worktree/SKILL.md)         |
| 「エージェントチームで」と指示された                   | [agent-team](.claude/skills/agent-team/SKILL.md)                 |
| テストコードを書く                                     | [vrcpilot-testing](.claude/skills/vrcpilot-testing/SKILL.md)     |
| CLI サブコマンドを足す / 引数や出力形式を変える        | [cli-design](.claude/skills/cli-design/SKILL.md)                 |
| CLI を実行する / パイプラインを組む                    | [vrcpilot-cli](.claude/skills/vrcpilot-cli/SKILL.md)             |
| README / docs/ / CHANGELOG を書く                      | [write-docs](.claude/skills/write-docs/SKILL.md)                 |
| 複数タスク・複数 file・長い bash 列に着手する          | [maximize-parallels](.claude/skills/maximize-parallels/SKILL.md) |

実機での end-to-end 手順は [memory/feedback_vrchat_cli_playbook.md](memory/feedback_vrchat_cli_playbook.md) に SSH / `.env` 環境での検証済み手順がある。
