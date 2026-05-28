---
name: screenshot-pinned-contract
description: screenshot.py の触れない境界 — pid 素通し / width-height は image 由来 / monitor_index 廃止は __post_init__ 警告 / save の YAML キー順
metadata:
  type: project
---

`src/vrcpilot/screenshot.py` は `mss` 除去リファクタ (Capture 化) 後、内部が既にクリーン。リファクタで「整えたく」なっても以下は **契約として pin 済み** で触ると壊れる。

- **`take_screenshot(*, pid=None)` は pid を resolve せず素通し**。`get_vrchat_window_rect(pid=pid)` → `Capture(pid=pid)` にそのまま渡す。理由: `VRChatMultipleInstancesError` は `VRChatNotRunningError` のサブクラス (subclass trap)。自前で `resolve_pid` + `except VRChatNotRunningError` すると多重起動エラーを握り潰す。`resolve_pid` 呼び出しを足してはいけない。
- **width/height は image 由来** (`image.shape[1]` / `[0]`)、x/y は rect 由来。rect の w/h (`_w`,`_h`) は意図的に捨てる。`image.shape == (height, width, 3)` を無条件成立させるため。`_`-prefix 捨て変数 + コメントが正しい表現。
- **例外マッピングは固定**: platform 判定 → Wayland-native は `RuntimeWarning`+`None` (Capture は raise する非対称が意図的) → rect None→None → `Capture.read()` の `except (RuntimeError, TimeoutError): return None`。`NotImplementedError` は伝搬。
- **`monitor_index` 廃止は `__post_init__` で非ゼロ時のみ `DeprecationWarning`** (候補 A)。メッセージに `"monitor_index"` と `"0.6.0"` 必須。`take_screenshot` は常に 0 を設定するので save/CLI パイプラインは無警告。属性アクセス時警告 (候補 B) や property (候補 C) に「改善」してはいけない — save/CLI が毎回読むため警告を撒き散らす / frozen dataclass で field と同名 property が共存不可。
- **`save()`/`load()` のロジックと YAML キー順は不変**: path-mode `path,x,y,width,height,monitor_index,captured_at` / inline-mode は `image` を最後。`load` の `cast(dict[str, Any], raw)` は yaml.safe_load の Unknown 対策で pyright strict 上必須。

**Why:** mss 除去 spec (`/tmp/vrcpilot-mss-spec.md` §2.1-2.3) がこれらを MUST で確定。テストが width=4/height=4 vs rect 800/600 で image 由来を直接 pin し、`pytest.warns(DeprecationWarning, match="0.6.0")` で廃止警告を pin している。
**How to apply:** このモジュールの refactor 依頼が来たら、上記は no-touch。残る改善余地は実質ない (import orphan なし / ruff clean / `>>>` doctest なし)。「クリーンなので無変更」が正解。
