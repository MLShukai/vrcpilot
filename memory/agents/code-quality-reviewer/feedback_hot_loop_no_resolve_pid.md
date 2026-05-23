---
name: hot-loop-no-resolve-pid
description: controls/clipboard で focus=False のとき resolve_pid を絶対に呼ばない hot-loop 規約と、その verification 観点
metadata:
  type: feedback
---

`vrcpilot.controls.mouse` / `vrcpilot.controls.keyboard` / `vrcpilot.clipboard` の公開関数は `focus=False` の **hot-loop 高速パス** で `vrcpilot.process.resolve_pid` を呼んではいけない (`ensure_target` も含めて完全にスキップ)。`resolve_pid` は内部で `psutil.process_iter` を走らせるため、フレーム単位で呼ばれると致命的なオーバーヘッドになる。

**Why:** psutil.process_iter は全プロセス列挙でコスト大。multi-instance PID 機能 (feature/20260523/multi-instance-pid) では引数に `pid` が追加されたが、これを「常に resolve_pid に渡す」と素朴に実装すると hot loop が劣化する。`focus=False` は「呼出側が既に focus 済みなので resolve も skip してよい」という明示的契約。

**How to apply:**

- `controls/mouse/__init__.py`, `controls/keyboard/__init__.py`, `controls/mouse/base.py`, `controls/keyboard/base.py`, `clipboard.py` の `focus=False` 経路で `ensure_target` / `resolve_pid` / `get_vrchat_window_rect(pid=...)` (絶対 move を除く) のいずれも呼ばれていないか確認する
- `clipboard.paste` は内部 `keyboard.press` を必ず `focus=False, pid=pid` で呼ぶ (二重 resolve 防止)
- `mouse.move` の absolute path のみ例外: `_to_desktop(pid=pid)` → `get_vrchat_window_rect(pid=pid)` は許容 (絶対 move 自体が rare path)
- テストは `mocker.patch("vrcpilot.process.resolve_pid")` を spy として置き、`resolve_spy.assert_not_called()` で hot-loop guarantee を検証する形が定番
- ensure_target は `pid: int | None` を受けて resolved PID (`int`) を返すので、呼出側がそれを window_rect lookup に reuse できる (race against VRChat exit の防止)
