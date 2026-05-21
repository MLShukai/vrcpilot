---
name: e2e は Claude が実行する
description: tests/e2e/ シナリオは人手作業として残さず、Claude 自身が `just e2e-test` で実行・検証する
type: feedback
---

`tests/e2e/` 配下の e2e シナリオは「実機 VRChat が必要だから人手検証」と扱わず、Claude セッション内で実行して動作確認・スクリーンショット確認まで行う。

**Why:** ユーザーから「人手作業とせずやるよう記憶してください」と明示指示あり (2026-05-02)。Linux 環境では SSH 越しでもデスクトップセッション (X11/XWayland) があれば `just e2e-test <NAME>` を実行可能で、`_helpers.save_monitor_screenshot` の出力 PNG を `Read` ツールで開けば視覚的確認まで Claude 側で完結する。「実機検証は別途人手で」と書いて手放すのは怠慢。

**How to apply:**

- 実装ステップで e2e シナリオを書いたら、続けて `just e2e-test <NAME>` を実行する
- SSH 越しでも `just e2e-test <NAME>` だけで OK。justfile が `DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" uv run python ...` の形でデフォルトフォールバックを持っているため、env を自分で前置する必要はない
- 出力 `_e2e_artifacts/<scenario>_<label>_<timestamp>.png` を `Read` ツールで開いて期待通りか検証する
- `PASS:` で終わっていてもスクリーンショット内容に異常があれば failure 扱いで再修正する
- 実機都合 (Steam 起動忘れ、Wayland native セッション、uinput 権限不足など) で失敗したらユーザーに環境を依頼するが、それは「人手検証」ではなく「環境セットアップ依頼」として明確に区別する
- エージェントを起動するときも「e2e シナリオの実行は本タスクの責任外」と書かない。実装エージェントには「書いて `just run` を pass させる」までを依頼し、`just e2e-test` は親 (Claude 本体) が実行する分担にする
