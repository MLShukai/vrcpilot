---
name: 許可済みコマンドを優先する
description: .claude/settings.json の permissions.allow に載っている形でツール呼び出しを組み立てる。リスト外のコマンドや絶対パスは毎回確認プロンプトが出て自走を止める。
type: feedback
---

`.claude/settings.json` の `permissions.allow` を毎セッション参照し、Bash・Read・Edit などのツール呼び出しはそのリストに収まる形に揃える。

**Why:** allow 外のコマンドや絶対パスは毎回確認プロンプトが出てユーザーの作業を中断させる。複数フェーズに分けた自走（実装 → review → commit → push → PR）では確認の数が線形に増え、CLAUDE.md の「自走開発フロー」が事実上機能しなくなる。allow リストは「いちいち聞かなくてよい」とユーザーが宣言した範囲であり、その内側で動くのが基本契約。

**How to apply:**

1. セッション開始時、または allow されているか怪しいコマンドを呼ぶ前に [.claude/settings.json](.claude/settings.json) の `allow` 配列を読む（`Bash(just:*)` / `Bash(git status|diff|log|show|branch|remote|tag|blame|rev-parse|commit|add|stash|checkout|switch|restore|fetch|pull|mv|check-ignore:*)` / `Bash(uv run pytest|pyright|pre-commit|vrcpilot:*)` / `Bash(uv add|sync|lock|build|pip show:*)` / `Bash(grep|find|tree|ls|cat|head|tail|wc|awk|file|stat|echo:*)` / `WebSearch` / `WebFetch` などが既に登録されている）。
2. `git -C <dir>` は `deny` なので使わない。cwd に居る前提でコマンドを書く。
3. Read / Edit / Write のファイルパスはプロジェクトルート相対で書く（絶対パス `C:\Users\...` は毎回確認になる）。Read tool 仕様上は絶対パスが必要なので、cwd からの相対パスで動かしたい場合は `src/vrcpilot/foo.py` のように書けば harness 側が展開してくれる。
4. allow リストに載っていない操作（新規 Bash サブコマンド、外部 CLI、書き込み系の git 操作で deny されているもの）が必要になったら、まずユーザーに「allow に追加するか別の手段を取るか」を相談する。勝手に try してプロンプトを誘発しない。
