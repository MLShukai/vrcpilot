---
name: keyboard.press の duration デフォルトは 0.1 秒
description: VRChat / Unity が短すぎる keypress をドロップするので keyboard.press の duration デフォルトを 0.0 にしない
type: project
---

`vrcpilot.controls.keyboard.press(key, *, duration=0.1)` のデフォルト値は **0.1 秒**。0.0 にすると VRChat (Proton/Wine 配下の Unity) がイベントを取りこぼす。

**Why:** 2026-05-02 の e2e (`tests/e2e/keyboard.py`) で `duration=0.0` (旧デフォルト) では ESC が VRChat に届かず LaunchPad が開かなかった。`duration=0.1` (inputtino の `Keyboard.type` の素のデフォルトと同値) に変えたら期待通り動作することをユーザーが確認・報告。inputtino 自体は 0.0 でも paired down/up イベントを発火するが、間隔が短すぎると Wine/Unity 側のイベントポーリングが拾い損ねる。

**How to apply:**

- `Keyboard.press` / module level `keyboard.press` の `duration` デフォルトは **`0.1`** を維持。`0.0` に戻さない
- mouse 側 (`Mouse.click(duration=0.0)`) はそのまま。mouse は 0.0 でも実機で動いた実績がある
- ホットループでより速くしたいユーザーが明示的に `duration=0.05` 等を渡すのは構わないが、**デフォルトは 0.1** で誰でも動く方を取る
- e2e シナリオ (`tests/e2e/keyboard.py`) はデフォルト `keyboard.press(Key.ESCAPE)` で動く前提。試行錯誤せずデフォルトに頼る
- 仕様書 `.claude/specs/controls.md` §4.2 が `duration=0.0` のサンプルを書いていても、本メモリに従って実装側は 0.1 を採用する (実機優先)
