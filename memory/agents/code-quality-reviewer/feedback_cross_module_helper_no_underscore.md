---
name: cross-module helper は `_` prefix を付けない
description: src 内の helper を別モジュールから呼ぶなら `_`-prefix を避ける。pyright reportPrivateUsage と reportUnusedFunction が同時に出る
metadata:
  type: feedback
---

`src/vrcpilot/` 内で関数を別ファイルに切り出して、別モジュールからその関数を呼ぶ場合、関数名に `_` prefix を付けてはいけない。pyright strict が

- 呼び出し側で `reportPrivateUsage`（"\_-prefixed をモジュール外から使った"）
- 定義側で `reportUnusedFunction`（cross-module 参照が "外部使用" としてカウントされない）

を **同時に** 投げる。両立しないので必ず非 `_` prefix にする。

**Why:** \[\[private モジュール規約\]\] は「テスト無し = `_` prefix」と定めているが、pyright の `reportPrivateUsage` はモジュール境界での `_`-prefix 参照を一律で warn にする。一方 `cli/_common.py` のように **モジュール自体** を `_` prefix にして中身を非 `_` で書くパターンは、import 元から見ると非 `_` 名を import するので両ルールに整合する。helper が単一モジュール内のみで使われるなら `_` で OK、cross-module になるなら名前から `_` を外す（公開はあくまで `__init__.py` の `__all__` で別管理）。

**How to apply:**

- 既存モジュール（例: `process/linux.py`）に helper を足して `process/launch.py` から呼ぶケース: helper は非 `_` prefix で命名する。`__all__` には足さない（外部公開はしない）。test を書かなくてもよい（既存 helper の薄い orchestrator なら統合テスト経由で十分カバーされる）
- 完全に単独モジュール内でしか使わない helper（例: `_wait_for_new_pid` in `launch.py`）はそのまま `_` で良い
- 「`tests/` から呼ぶ可能性があるか」で判断するのが prefix 規約だが、それ以前に「cross-module で呼ぶか」を見る方が pyright 警告の有無で即決できる

**実例 (2026-05-25):** `process/linux.py` に `resolve_direct_spawn_wineprefix` を新設して `process/launch.py` から import。初回は `_resolve_direct_spawn_wineprefix` と命名して上の 2 警告を踏んだ。リネーム + `__all__` 非登録で解決。
