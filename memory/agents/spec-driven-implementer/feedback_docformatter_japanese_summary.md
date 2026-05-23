---
name: docformatter は Japanese 全角句点を summary 末尾で勝手に . に置換する
description: docformatter (pre-commit) は docstring summary が `。"""` で終わると `。."""` を追加し、その後で wrapping を再実行して 2 行に折る — summary は ASCII `.` で締める
metadata:
  type: feedback
---

`uv run pre-commit run -a` の `docformatter` フックは、Python docstring の
summary が日本語の全角句点 `。` で終わる場合に `。."""` のように ASCII の
`.` を強制的に追加する。長い summary が allowed-length (line-length 88 を考慮)
を超えると、その後 wrapping を実行して summary が **2 行** に折れる
(例: `"""...バリデーション` / `を送出)."""`)。一度この状態になると `pyright`
は通るが、見た目が極端に悪く後続の自分の Edit でも復元しづらい。

**Why:** docformatter の "summary 末尾は必ず . で終わるべき" ルールが Unicode
の全角句点 (`U+3002`) を文末記号として認識せず、ASCII `.` を強制追加するため。

**How to apply:**

- `src/vrcpilot/` 配下の Python docstring を新規に書く / 編集するとき、
  summary 行 (1 行目) を **ASCII `.` で締める** か、句読点を付けない (PEP 257
  は summary が完結した命令文であれば period を要求するが、`docformatter` は
  どちらも受け入れる)。日本語 docstring でも summary 末尾だけは `.` を使う。
- 本文 (summary 以降の段落) は `。` で終わって OK。docformatter は body には
  ピリオド追加しない。
- 既に `。."""` の二重句点に折れた docstring を見たら、`。` を削って `.` だけ
  残し、必要なら summary を line-length 88 − インデント (4) − `"""` (3) ≈ 81
  以下に収まるよう短縮する。

例: ``` """``launch()`` 引数の fail-fast バリデーション.""" ``` ← `."""` で締める
ことで docformatter が二重 wrap しない。
