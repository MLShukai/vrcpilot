---
name: pyright ignore の集約・最小化
description: src 配下で `# pyright: ignore` を集約・削減する際に有効だったテクニックと既知の落とし穴
type: feedback
---

stub のない C 拡張・PyO3 モジュール（`windows_capture`、`win32api` の一部、python-xlib 等）は使用箇所ごとに `reportUnknown*` / `reportAttributeAccessIssue` 等を撒き散らす。1 箇所ずつ ignore する代わりに、一度だけ `Any` に widen することで連鎖を止められる。

**Why:** `# pyright: ignore` を各使用箇所に書くと「なぜこれが必要か」が散漫になり、新しい使用箇所を追加するたびに同じ ignore を書く誘惑が生まれる。型情報を 1 箇所で意図的に放棄する方が、レビュアーにも将来の自分にも親切。

**How to apply:**

- モジュール全体の symbol を Any にしたい場合: `from x import Y as _YRaw` してから `Y: Any = _YRaw` を直後に置く。元の名前を残せばテストが `mocker.patch("module.Y", ...)` で patch していても壊れない（重要）
- 関数 1 つを Any 化する場合: `fn = cast(Any, module).attr` と書く。`cast(Any, module.attr)` だと `module.attr` の参照自体が `reportUnknownMemberType` で先に落ちるので、まず `module` を Any 化すること
- argparse の動的属性アクセス（`action.completer = ...` 等）: `setattr(action, "completer", value)` でラップ。ruff B010（"setattr with constant attribute"）が出るので `# noqa: B010 - 理由` を添える。型: ignore の代わりに lint: ignore に置換しているだけだが、後者は ruff の lint カテゴリなので意図が明確
- デコレータで登録する未使用ハンドラ（`@capture.event def on_x(): ...`）の `reportUnusedFunction` は、関数定義の直後に `_ = on_x` と書くと黙る。アンダースコアプレフィックス（`_on_x`）への改名は呼び出し側 API を壊す可能性があるので避ける
- PyO3 モジュールの `reportMissingTypeStubs` は import 行に残すしかない（stub を生やすしかない）。残す ignore には冒頭コメントブロックで「なぜ stub が無いのか」「Any 化の波及範囲はどこまでか」を 1 度だけ説明する

**残してよいパターン（テスト側）:**

- argparse private 属性アクセス（`_actions` 等）の検証
- frozen dataclass の上書き検証（意図的に `dataclasses.FrozenInstanceError` を踏みに行く）
- 多重継承テストダブル（Xlib `_NoArgXError` 等、stub の都合で `# type: ignore[misc]` が必要）
- これらは「正しいことをテストするために必要な ignore」なので削減対象から外す
