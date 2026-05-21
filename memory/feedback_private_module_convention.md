---
name: private モジュール規約
description: src/vrcpilot/ における `_` prefix 命名規約 — モジュールでも関数でも、テスト有無で prefix を決める
type: feedback
---

`src/vrcpilot/` 配下では **モジュールでも module-level 関数でも**、テストから参照されるかどうかで `_` prefix の有無を決める:

- テストを書かない（真に private な実装）→ `_` prefix を付ける（例: `cli/_common.py`、module-private な `_get_default_engine` / `_decide_text_color`）
- テストを書く / 書かれている → `_` prefix を **付けない**（例: `steam.py`, `win32.py`, `x11.py`, `session.py`, `capture/sinks.py`、テストから直接呼ぶ `build_parser`）
- 外部公開は `__init__.py` の `__all__` で別途集約管理する。`_` 有無と「公開 API」は独立した軸として扱う

**Why:** `tests/` から `_`-prefixed なものを import / 呼び出しするのは「テストする = 外部からも触り得る」ことを意味し、prefix の本来の意図（"do not test, do not touch"）と矛盾する。命名規約として一貫させ、誤誘導を防ぐ。`__all__` で公開面を制御していれば、内部の名前から `_` を外しても外部に漏れることはない。

**How to apply:** モジュールや関数を新設する時、テストを書くか即決する。テストを書くつもりなら `_` 無しの名前にする。逆に誰にも触らせたくない実装は `_` を付けてテストも書かない。既存名でテストを追加する場合は、リネーム + importer / caller 修正をセットで行う（公開 API として `__init__.py` の `__all__` に足すかは別判断）。

実例: 2026-05-03 の cli リファクタで、`__init__.py` 内の `_build_parser()` は `tests/vrcpilot/cli/test_init.py` から直接呼ばれていたので `build_parser` に rename。ただし `__all__` には載せず、外部 API は `main` のみに保つ。

## tests/ 配下では適用しない

この規約は `src/vrcpilot/` 専用。`tests/` には「外部公開」の概念が無いので `_` prefix は基本的に**付けない**:

- `tests/helpers.py` / `tests/fakes/` / `tests/conftest.py` — prefix 無しで揃える
- 例外: `tests/e2e/_helpers.py` は **`just e2e-test <NAME>`** が `tests/e2e/<NAME>.py` を直接実行する仕組みになっており、prefix 無しだと `just e2e-test helpers` が誤実行されうる。同階層の `all.py` / `focus_unfocus.py` 等の **実行可能シナリオ** と区別する語彙として `_` を残す

**判断基準:** `tests/` 内で `_` を付けるのは「機能的に prefix が役立つ場合」(例: 直接 script 実行されるディレクトリ内でのヘルパー識別) のみ。「外部から触らせない」目的で `_` を付けない。
