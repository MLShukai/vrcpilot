---
name: github-pr
description: gh CLI を使った vrcpilot の PR 作成・確認・レビュー対応と issue 操作。gh は PATH に無いので絶対パスで呼ぶ、HEREDOC でのフォーマット崩れ回避、PR テンプレート、4 本の CI ワークフローとローカル再現コマンドの対応、安全規約。PR を出す / CI 結果を見る / issue を操作する前に読む。
---

# PR を送る (gh CLI)

[git-ops](../git-ops/SKILL.md) の規約を `gh` 操作に落とし込んだ手順。リポジトリは `MLShukai/vrcpilot`。

## 0. `gh` の呼び方

`gh` は PATH に通っていない環境がある。`command not found` で諦めず絶対パスを試す:

```bash
"/c/Program Files/GitHub CLI/gh.exe" --version    # Windows + Git Bash
```

詳細は [memory/reference_gh_executable_path.md](../../../memory/reference_gh_executable_path.md)。以下 `gh` と書いた箇所はこの解決済みパスに読み替える。

## 1. 前提

```bash
gh auth status                # 認証済みか
git branch --show-current     # main でないこと
git status --short            # 空 (clean) であること
just run                      # green であること
```

PR を出す直前に `main` を取り込む → [merge-main](../merge-main/SKILL.md)。

## 2. push する

```bash
git push -u origin HEAD    # 初回。-u で upstream を貼る
git push                   # 2 回目以降
```

## 3. PR を作成する

body は [.github/PULL_REQUEST_TEMPLATE.md](../../../.github/PULL_REQUEST_TEMPLATE.md) に従う。

```bash
gh pr create \
  --base main \
  --title "<種別>(<スコープ>): <内容>" \
  --body "$(cat <<'EOF'
## Summary

- <変更点 1 つ目>
- <変更点 2 つ目>

## Test plan

- [ ] `just run` が green (format / test / type)
- [ ] (実機に関わる場合) `just e2e-test <NAME>` が green + スクリーンショット確認済み

## Notes

<レビュアーに知っておいてほしい判断・トレードオフ・未解決事項>
EOF
)"
```

- **`--body "$(cat <<'EOF' ... EOF)"` のシングルクォートが要**。無いと `$` やバッククォートが shell に展開される
- タイトルはコミットメッセージと同じ形式。`--draft` で WIP 化できる
- 複数コミットを含むブランチでは body で全体を要約する (タイトルは支配的な変更を反映)
- hotfix PR は `release/x.y` を base にし、`[ ] cherry-picked to main` を含める ([CONTRIBUTING.md](../../../CONTRIBUTING.md) の Hotfix process)

### CI が見るもの

| ワークフロー                                    | ローカルでの再現               |
| ----------------------------------------------- | ------------------------------ |
| `pre-commit.yml`                                | `just format`                  |
| `type-check.yaml`                               | `just type`                    |
| `test.yml` (Linux / Windows × Python 3.12–3.14) | `just test`                    |
| `publish.yml`                                   | タグ push 時のみ。手で叩かない |

`test.yml` が特定 OS だけ落ちるなら platform 分岐 (`windows.py` / `linux.py`) か cp932 / SSH 環境の癖を疑う。`gh run view <id> --log-failed` で落ちたジョブだけ読む。e2e は CI では走らない (実 VRChat が必要) ので、実機検証はローカルの `just e2e-test` が唯一のゲート。

## 4. 確認・レビュー

```bash
gh pr list
gh pr view <番号> --comments
gh pr diff <番号>
gh pr checks <番号> --watch          # CI 完了まで follow
gh api repos/MLShukai/vrcpilot/pulls/<番号>/comments   # inline review コメント

gh pr review <番号> --comment --body "..."
gh pr review <番号> --approve
gh pr review <番号> --request-changes --body "..."
```

CI が長いときは `gh pr checks <番号> --watch` をバックグラウンドで走らせる。

## 5. issue 操作

```bash
gh issue create --title "..." --body "..."   # テンプレは .github/ISSUE_TEMPLATE/
gh issue list --state open
gh issue view <番号> --comments
gh issue comment <番号> --body "..."
```

セキュリティ脆弱性は public issue ではなく GitHub Security Advisories に出す ([CONTRIBUTING.md](../../../CONTRIBUTING.md))。

## 6. 安全規約

- **`main` への直接 push / force-push をしない**。指示されても作業ブランチを切って PR にする
- **`gh pr merge` / `gh pr close` はユーザー判断**。自発的にマージ・close しない
- `gh release create` / `v*` タグ push はリリース手順が担う。手で叩かない ([docs/RELEASE.md](../../../docs/RELEASE.md))
- `gh repo edit` などのリポジトリ設定変更はユーザー確認
- PR body / commit body に `.env` の中身や secret を貼らない

## 7. トラブルシュート

| 症状                                                         | 対処                                                         |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| `gh: command not found`                                      | 絶対パスで呼ぶ (§0)                                          |
| `HTTP 401: Bad credentials`                                  | `gh auth status`。トークン期限切れ / scope 不足              |
| `Updates were rejected because the remote contains work ...` | [merge-main](../merge-main/SKILL.md) で取り込んでから再 push |
| pre-commit が push を遮る                                    | 落ちた hook の根本原因を直す。`--no-verify` で迂回しない     |

## 8. ローカル PR ドラフト

API を叩く前に手元で内容を固めたいとき:

```bash
git log main..HEAD --oneline      # PR に含まれる commits
git diff main...HEAD --stat       # 変更ファイルの概観 (... に注意)
```
