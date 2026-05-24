---
name: feedback-env-var-prefix-permission
description: Bash で `env -u FOO bar` / `FOO=val bar` のように env var prefix を付けるたびに permission が求められる。繰り返すなら export しておく
metadata:
  type: feedback
---

`env -u DISPLAY uv run pytest ...` や `FOO=bar baz ...` のように **コマンド先頭に env 変更子** を付けると、harness の permission gating でその都度確認プロンプトが上がる。同じ env で複数コマンドを連続実行する場合は不便。

**Why**: 環境変数 prefix は実質的に「コマンドを変更している」と認識されるため allowlist パターンにマッチしづらく、同一フォーム (`env -u DISPLAY -u XAUTHORITY uv run pytest ...`) を毎回確認する羽目になる。export なら以降の `uv run pytest` 自体は通常 allowlist に乗る。

**How to apply**: 同じ env override を 2 回以上行う見込みなら、先に `export FOO=bar` / `unset FOO` を 1 度だけ実行して shell に固定し、以降のコマンドは prefix なしで叩く。1 回限りなら prefix のままで OK。

(2026-05-24 のセッションで `env -u DISPLAY uv run pytest ...` を続けて打とうとして指摘されたフィードバック)
