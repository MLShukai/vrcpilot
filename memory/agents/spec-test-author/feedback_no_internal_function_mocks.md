---
name: 自分のコードの内部関数モック禁止の実例 (controls 周辺)
description: ensure_target / is_wayland_native / resolve_pid / window.is_foreground / get_vrchat_window_rect は vrcpilot 自前の関数。mocker.patch せず、autouse fixture / real X11 / e2e で代用するパターン集
metadata:
  type: feedback
---

新方針 (skill) で「自分のコードの内部関数モック禁止」になった結果、controls 周辺で取った代替手段。

**Why:** ensure_target / resolve_pid / window.\* / is_wayland_native / get_vrchat_window_rect はすべて vrcpilot が所有する関数。`mocker.patch("vrcpilot.controls.guard.window.is_foreground", return_value=True)` のような旧パターンは「リファクタで壊れるだけで何も保証しない」ためトリッキーに置き換える必要があった。実装に着手するエージェントが同じ罠を踏まないよう、置き換えパターンを記録しておく。

**How to apply:**

- **`ensure_target` を踏みたい / 踏みたくない**:
  - `focus=False` で skip し、ABC sequencing は ImplKeyboard / ImplMouse で純粋に検証
  - `focus=True` の挙動証明は autouse `_no_real_vrchat` fixture が `resolve_pid(None)` → `VRChatNotRunningError` を引き起こすので、`with pytest.raises(VRChatNotRunningError):` で「guard が走った」ことを観測できる
- **`resolve_pid` の特定 PID 経路**: pid を渡すと resolve_pid は即 return するので、その先の `window.is_foreground(pid=X)` まで到達する。X11 + 実 focusable window が必要なので unit では検証せず e2e に委譲
- **`is_wayland_native`**: 実 Wayland session でしか踏めない。`pytest.skip` で X11 host を弾く + Wayland 限定テストを 1 つ残すパターン
- **`get_vrchat_window_rect`**: mouse の絶対座標変換 (`_to_desktop`) で必要。window/Xlib + 実 VRChat が要るので unit テストは relative 経路のみ、絶対経路は e2e (`tests/e2e/mouse.py`) に委譲
- **`time.sleep` / `time.monotonic`**: stdlib も 3rd-party 扱いでモック禁止。`duration=0.0` を渡せば skip される実装なら活用、デフォルト値の意味検証 (`duration=0.1` is non-zero) は実際に sleep して `time.monotonic` の差分を assert する (0.05 s 程度の loose lower bound)

ボツにした例外:

- `monkeypatch.setattr(sys, "platform", "freebsd")` は `_get()` の unsupported-platform 経路に到達する唯一の手段だが、skill で `sys.platform` の monkeypatch を明示的に禁止しているので使わない。その branch は「unsupported platform でしか踏まれない defensive raise」として unit からは諦める

関連: [feedback_test_classes.md](feedback_test_classes.md), [feedback_boundary_assertions.md](feedback_boundary_assertions.md)
