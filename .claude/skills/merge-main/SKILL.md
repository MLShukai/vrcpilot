---
name: merge-main
description: PR を出す直前に origin/main を作業ブランチへ取り込みコンフリクトを解消する手順。rebase ではなく merge を使う方針、uv.lock / CHANGELOG / pyproject version / memory と .claude 配下のコンフリクト解消法、取り込み後の再検証。main を最新化する / コンフリクトを解消する前に読む。
---

# PR の直前に main を取り込む

作業の最後、PR を出す **直前** に `origin/main` を作業ブランチへ merge する。これで PR が最新の base に対して clean に diff する。

[git-ops](../git-ops/SKILL.md) と整合。**`main` への直接 commit / push はしない**。取り込みは作業ブランチ側で行う。

このリポジトリは **rebase ではなく merge** を既定とする (merge commit を許容し、自ブランチの commit hash を書き換えない)。rebase が必要な特殊事情があるなら理由をユーザーに確認してから。

## 手順

```bash
git status --short                  # 空 (clean) であること
git branch --show-current           # main でないこと
git fetch origin main
git log HEAD..origin/main --oneline # 空なら取り込み不要。そのまま PR へ
git merge origin/main
```

`git pull` ではなく `fetch` + `merge origin/main` を使う (ローカル `main` を介さない)。

## コンフリクト解消

```bash
git diff --name-only --diff-filter=U    # conflict した file 一覧
```

**両者の意図を保持する。** `--ours` / `--theirs` で機械的に片方を採るのは、本当にもう一方が不要か確認してから。判断が割れるコンフリクト (両方が同じ関数を別意図で書き換えた等) は勝手に決めず、何が衝突しているか名指しでユーザーに確認する。

解消したら `git add <file>`、全部済んだら `git merge --continue`。中断は `git merge --abort`。

| 対象                                          | 解消方法                                                                                                  |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `uv.lock`                                     | **手で潰さない**。`pyproject.toml` を先に解消してから `uv lock` を再実行し、その結果で上書きする          |
| `pyproject.toml` の `version`                 | `main` (リリース側) の値を採る。作業ブランチで上げていたならリリース手順の逸脱なので見直す                |
| `CHANGELOG.md` の `## [Unreleased]`           | 両方のエントリを残す。順序は問わない                                                                      |
| `docs/*.md` と `docs/*.ja.md`                 | 片方だけ解消して終わらない。対訳ペアなので両方に同じ変更を反映する → [write-docs](../write-docs/SKILL.md) |
| `memory/` `.claude/skills/` `.claude/agents/` | 両者の意図を読んで統合する。片方を機械的に採らない                                                        |

## 取り込み後の検証

テキストコンフリクトが無くても論理は壊れうる。**省略しない**。

```bash
just run                   # format → test → type
just e2e-test <NAME>       # 実機の振る舞いに関わる変更が両側にあった場合
```

テストが落ちたら、`main` 側の変更と自分の変更の **意味的な衝突** を疑う (例: 片方が backend ファイルをリネームし、もう片方が旧名を参照している)。

## やってはいけないこと

- ローカル `main` に commit / push する
- コンフリクトを `git checkout --theirs .` 等で一括上書きする
- コンフリクトマーカーを残したまま `git add` / commit する
- 取り込み後に `just run` を省略する
- `git push --force` (merge による取り込みは履歴を書き換えないので force は不要)

以降は [github-pr](../github-pr/SKILL.md) の `gh pr create` 手順へ。
