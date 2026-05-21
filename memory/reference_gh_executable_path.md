---
name: gh CLI は絶対パスで呼ぶ
description: GitHub CLI (`gh.exe`) は PATH に通っていないが `C:\Program Files\GitHub CLI\gh.exe` に存在する。bash からは `"/c/Program Files/GitHub CLI/gh.exe"` で呼ぶ。
type: reference
---

PR 作成や issue 操作で `gh` を使う場合、Windows + Git Bash 環境では `command -v gh` も `where gh` も解決しない（PATH 未登録）。ただし `gh.exe` 本体は `C:\Program Files\GitHub CLI\gh.exe` にインストール済み。

bash 経由での呼び出し方:

```bash
"/c/Program Files/GitHub CLI/gh.exe" pr create --title "..." --body "..."
"/c/Program Files/GitHub CLI/gh.exe" pr view <num>
"/c/Program Files/GitHub CLI/gh.exe" api repos/<owner>/<repo>/issues
```

検証コマンド:

```bash
"/c/Program Files/GitHub CLI/gh.exe" --version
# → gh version 2.92.0 など
```

`gh` が `command not found` を返したら諦めず、絶対パスを試す。
