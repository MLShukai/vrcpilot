---
name: claude-config-opus5-conventions
description: .claude/agents と .claude/skills の書き方。model は inherit 固定、harness の memory prompt をコピペしない、tools を列挙しない、自己チェックリストを書かない、詳細は skill に progressive disclosure する
metadata:
  type: feedback
---

`.claude/agents/*.md` と `.claude/skills/*/SKILL.md` は Claude 5 世代 (Opus 5 以降) を前提に書く。2026-08-22 の migration で以下を確定させた。

**Why:** Anthropic の Claude 5 世代向けガイダンスは「unhobbling」— 過剰指定・重複・prescriptive なルールを削り、モデルの判断に委ねる方向。Claude Code 自体の system prompt も 80% 以上削られている。加えて Opus 5 は自己検証を指示なしで行うため、明示的な verification 指示は over-verification を招いて無駄にトークンを焼く。

**How to apply:**

- **`model: inherit`** を使う。`opus` などモデル名を agent 側に焼き込まない。世代が変わるたびに全 agent を追従更新する羽目になる。意図的に軽いモデルへ落とす場合だけ例外として明示 pin し、理由を書く
- **`tools:` を列挙しない**。省略して継承させる。MCP auth ツールまで並べた allowlist は harness 側の変更で腐る
- **`memory:` frontmatter は使わない**。harness が `.claude/agent-memory/<name>/` (gitignore 済み) を注入してしまい、repo 追跡の `memory/agents/<name>/` 規約と二重になる。代わりに agent 本文で `memory/agents/<name>/MEMORY.md` を読む / 書くよう明示する
- **harness の memory prompt (`# Persistent Agent Memory` 以下) をコピペしない**。以前は 5 agent × 約 150 行の stale なコピーが入っており、参照先も間違っていた
- **「自己チェック (報告前に実行)」チェックリストを書かない**。`just run` のような **プロジェクトの品質ゲート** は書いてよいが、「報告前に再確認する」「ダブルチェックする」類の指示は削る
- **例示を盛らない**。`description` に `<example>` ブロックを 3 つ積むと探索空間を狭める。dispatch に必要な「何をする agent か / いつ使うか」だけ書く
- **詳細は skill へ progressive disclosure する**。agent 本文に testing 方針や git 手順を再掲せず、`.claude/skills/` を参照する。CLAUDE.md も同様に「repo の簡潔な説明 + 非自明な gotcha + skill 索引」に絞る
- **重複を作らない**。同じ規約を CLAUDE.md と agent と skill の 3 箇所に書かない。1 箇所を正として残りはリンクする

関連: \[\[feedback_private_module_convention\]\], \[\[feedback_planning_doc_language\]\]
