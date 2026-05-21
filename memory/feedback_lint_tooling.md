---
name: lint / format ツーリングは pre-commit で一括
description: ruff / docformatter / mdformat / codespell 等は pre-commit に統合済みなので個別に列挙しない
type: feedback
---

`just format` は `pre-commit run -a` を呼ぶラッパで、ruff (lint + format)・pyupgrade・docformatter・mdformat・codespell・uv-lock など全 hook を実行する。`just run` は `format → test → type` の連結。

**Why:** ユーザーから「ruff は pre-commit に入っていますよ」と指摘あり (2026-05-02)。指示や報告で「ruff」「docformatter」「pre-commit」を別項として列挙すると冗長で、フックの実体を理解していないように見える。

**How to apply:**

- エージェント prompt や検証手順では「`just run` を pass」「`pre-commit` 全 hook green」のような **集約形** で書く
- ruff / docformatter / mdformat 等を個別の検証項目として列挙しない（pyright は `just type` 経由で別工程なので別記載 OK）
- レビュー報告でも「ruff green、docformatter green …」と並べず「pre-commit 全 hook green」「`just run` green」で済ます
- 設定変更（line-length 等）の話題ではフック名を出してよい。日常的な検証の文脈では集約する
