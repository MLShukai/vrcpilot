---
name: named-callback-helper-inline-when-single-caller
description: ExitStack-callback 用に named wrapper を保つ場合、共有 body を持つ helper は caller 1 つになった時点でインライン化する。frame 名は wrapper が担う
metadata:
  type: feedback
---

`_safe_unload_*` 系の「named wrapper + 共有 body 関数」パターンは、wrapper
が 2 つ以上ある間は意味があるが、1 つだけになった時点で body 関数は単な
る indirection に縮退する。caller 1 になったら body をインライン化する。

**Why:** `vrcpilot.speaker.linux` で loopback 廃止により
`_safe_unload_by_attr(attr_name, module_label)` の caller が
`_safe_unload_null_sink` のみになった。docstring-author の memory
(`project_speaker_linux_per_pid` の "Thin delegators" 節) には「frame 名
が ExitStack callback / traceback 上で重要だから wrapper を残せ」と書か
れていたが、これは **wrapper** に対する要件であって、内側の共有 body 関数
が必要だという話ではない。共有 body は重複が 2 つあるからこそ意味がある。
1 caller になると `getattr(self, attr_name)` / `setattr(...)` の動的アク
セスが「読みにくい」「pyright が attribute を辿れない」「concrete な
attribute 名を読み解く一手間が増える」だけで、得るものがない。

**How to apply:** ExitStack 系の「named callback 」を保つときは:

1. wrapper メソッド名は ExitStack callback / traceback frame に出る重要
   情報なので保持する (frame 名の rationale はその wrapper の docstring
   に置く)
2. wrapper が 2 つ以上残っているなら共有 helper (`_safe_unload_by_attr`
   風) は OK
3. wrapper が 1 つだけになったら helper は **インライン化** する。
   `getattr`/`setattr` 経由の動的 attribute access は concrete field 名
   に置き換える。pyright が型を辿れる、grep しやすい、indirection が 1
   段減る、warnings.warn の label もリテラル化される

docstring-author の `project_speaker_linux_per_pid.md` にある "Thin
`_safe_unload_loopback` / `_safe_unload_null_sink` delegators" 節は
**loopback 時代のスナップショット** であり、helper を残せという指示で
はなく「frame 名を残せ」という指示として読む。loopback 廃止後は
`_safe_unload_null_sink` だけが残り、helper はインライン化済み。
