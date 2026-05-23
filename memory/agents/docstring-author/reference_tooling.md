---
name: docformatter and pyright caveats for docstring work
description: docstring 作業者が踏まえるべき docformatter のリフロー挙動と pyright strict の制約。`just` レシピや pre-commit 集約の一般論は memory/feedback_lint_tooling.md を参照
metadata:
  type: reference
---

共有メモリ [`memory/feedback_lint_tooling.md`](../../feedback_lint_tooling.md) が
`just` レシピと pre-commit 集約のルールを定める。本ファイルは docstring 作業に
固有の差分のみを記述する。

**Docformatter quirks observed:**

- Wraps prose at line-length 88 and rewrites the summary line to fit on the
  first line. Avoid summaries that can be split awkwardly.
- Preserves doctest blocks exactly — safe to include `>>>` lines without
  docformatter mangling them.
- `just format` は内部で docformatter を呼ぶので、書いた docstring が in-place
  で書き換わる。書き換え後を確認してから再 stage する。

**Pyright strict surface（docstring 視点）:**

- 対象は `./src/` のみ（`tests/` は除外）。
- `reportImplicitOverride` 有効、`reportPrivateUsage` は警告。
- docstring の本文が type hint と矛盾してはいけない（例: シグネチャが `str` を
  返すのに「returns `None`」と書く等）。

**Commit 時の注意:**

- `--no-verify` で hook を skip しない。docformatter / ruff が in-place 書き換え
  をしたら restage して commit を作り直す（amend ではなく新規コミット）。
