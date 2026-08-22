---
name: git-ops
description: 'vrcpilot の git 運用。ブランチ命名 (種別/YYYYMMDD/内容)、コミットメッセージ形式 (種別(スコープ): 内容)、main 直コミット禁止、コミット前の `just run` ゲート、uv.lock / pyproject version / .claude と memory の追跡対象、やってはいけない操作。tracked file に書き込む作業 (実装・リファクタ・docs 修正・commit・ブランチ切り) を始める前に読む。'
---

# git 運用

**tracked file を変更しうる作業に着手する前に読む。** `main` の上で実装を始めてしまうと巻き戻しが面倒になる。

## ブランチ

- `main`: 唯一の長寿命開発ブランチ。**直接 commit しない**
- 作業ブランチ: `<種別>/<YYYYMMDD>/<内容>`
  - 種別: `feat` / `fix` / `refactor` / `docs` / `test` / `chore`
  - 例: `feat/20260822/osc-avatar`、`fix/20260822/launch-timeout`

```bash
git branch --show-current                        # 今どこにいるか
git switch -c feat/$(date +%Y%m%d)/<slug> main
```

`main` の上にいることに気付いたら、実装を始める前にブランチを切る。既に `main` で編集してしまっていても、`git switch -c <branch>` すれば未コミットの変更はそのまま新ブランチに移る。

**`main` へのマージはユーザーが判断・実行する。** 自発的に `gh pr merge` は叩かない。

`release/<x.y>` ブランチと hotfix / リリースタグの運用は [CONTRIBUTING.md](../../../CONTRIBUTING.md) と [docs/RELEASE.md](../../../docs/RELEASE.md) が正。ここでは重複させない。

## コミットメッセージ

`<種別>(<スコープ>): <内容>` の形式に従う。本文は日本語でよい。

- 種別: `feat` / `fix` / `docs` / `style` / `refactor` / `test` / `chore`
- スコープ: サブパッケージ名またはファイル単位。`speaker/linux`、`cli,api` のように細かく / 複数書いてよい
- 例: `feat(osc): アバターパラメータ送信を追加`、`fix(speaker/linux): per-PID 録音の無音化を解消`

**1 コミットに複数の関心事を混ぜない。** 実装 / テスト / docs は同じ機能に属していても、分けられるなら分ける。

## コミット前のゲート

```bash
just run          # format (pre-commit 全 hook) → test → type
```

実機の振る舞いに関わる変更 (`controls/` / `capture/` / `speaker/` / `mic/` / `window/` / `process/` / `cli/`) なら、加えて該当シナリオを回してスクリーンショットまで確認する:

```bash
just e2e-test <NAME>       # tests/e2e/<NAME>.py。NAME 省略で all
```

テストが赤いままコミットしない。`git commit --no-verify` は使わない (pre-commit が落ちた根本原因を直す)。

## このリポジトリの追跡対象

| 対象                                                                       | 扱い                                                                                                                           |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `uv.lock`                                                                  | **コミットする**。`pyproject.toml` を触ったら `uv lock` の差分を同じコミットに含める (pre-commit の `uv-lock` hook が検出する) |
| `pyproject.toml` の `[project].version`                                    | バージョンの単一の真実。上げるのはリリース時のみ。他の場所にハードコードしない (`tests/vrcpilot/test_init.py` が強制)          |
| `memory/`                                                                  | **コミットする**。プロジェクト / エージェントの知見はチーム共有資産                                                            |
| `.claude/agents/` `.claude/skills/` `.claude/settings.json`                | **コミットする**。チーム共有の Claude 設定                                                                                     |
| `.claude/settings.local.json` `.claude/agent-memory/` `.claude/worktrees/` | gitignore 済み。個人環境 / harness 管理下                                                                                      |
| `dist/` `_e2e_artifacts/` `.env` `.coverage`                               | gitignore 済み。成果物・実行ログ・個人設定はコミットしない                                                                     |

エージェントが得た知見は gitignore 済みの `.claude/agent-memory/` ではなく **`memory/agents/<name>/`** に書く。前者に書くとチームに共有されない。

## やってはいけないこと

- `main` に直接 commit / push する
- `git push --force` / `-f` (履歴破壊)。rebase 直後にどうしても必要なら `--force-with-lease`、共有ブランチには使わない
- `git reset --hard` / `git clean -f` で未コミットの作業を捨てる (`.claude/settings.json` の deny リストでも禁止)
- `git commit --no-verify` / `git push --no-verify` で hook を迂回する
- コンフリクトマーカー (`<<<<<<<`) が残ったまま `git add` する (pre-commit の `check-merge-conflict` が拾うが、そもそも作らない)
- `git --no-pager` を付ける (非 TTY の Bash では git が自動で pager を bypass するので冗長)

## 関連

- main の取り込み → [merge-main](../merge-main/SKILL.md)
- PR 作成・レビュー → [github-pr](../github-pr/SKILL.md)
- worktree 隔離 → [do-on-worktree](../do-on-worktree/SKILL.md)
