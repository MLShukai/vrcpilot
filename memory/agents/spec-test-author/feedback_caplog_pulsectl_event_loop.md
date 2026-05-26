---
name: caplog around pulsectl backend constructor not internal methods
description: PipeWireSpeakerBackend で diagnostic log を assert する時は __init__ を caplog で包む。event_listen thread が走り出した後に internal sync method を呼ぶと pulsectl が PulseLoopStop で blocking 拒否する
metadata:
  type: feedback
---

`PipeWireSpeakerBackend` の `_enumerate_vrchat_sink_inputs` や `_move_existing_streams_to_tap` のような pulsectl sync API を内部で叩くメソッドを、テストから直接呼んで diagnostic log を caplog で検査しようとすると失敗する。

**症状**: `WARNING vrcpilot.speaker.linux:linux.py:549 sink_input_list failed: Running blocking pulse operations from pulse eventloop callbacks or other threads while loop is running is not supported by this python module.`

**原因**: 親 `__init__` の `ExitStack` で `_event_thread.start()` (line ~268) が走り、その thread の中で `pulse.event_listen()` が blocking pull に入る。その後にメインスレッドから `pulse.sink_input_list()` 等を呼ぶと pulsectl がブロックを拒否する。`_enumerate_vrchat_sink_inputs` は冒頭で try/except して early return するので、その先の summary ログが emitted されない。

**対処**: diagnostic log の assertion は **コンストラクタ呼出を caplog で包む** のが正解。`__init__` 内で `_move_existing_streams_to_tap` が `_event_thread.start()` の **前に** synchronous に走るので、その時の summary log が確実に caplog に入る。

```python
with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
    caplog.clear()
    backend = PipeWireSpeakerBackend(pid=my_pid)
    try:
        summaries = [
            rec.getMessage()
            for rec in caplog.records
            if rec.name == "vrcpilot.speaker.linux"
            and "sink_input scan summary" in rec.getMessage()
        ]
    finally:
        backend.close()
```

**Why:**

- pulsectl は event loop thread と sync API を 1 接続から並行で叩くと壊れる仕様 (これは 3rd-party の制約で vrcpilot のバグではない)
- コンストラクタ内の synchronous phase (`_load_null_sink` → `_move_existing_streams_to_tap`) は event thread 起動前なので caplog で安全に観測できる
- internal method を直接呼ぶアプローチは pulsectl 制約に引っかかる + 「コンストラクタが既に同じ仕事をやっている」ので二度手間

**How to apply:**

- `vrcpilot.speaker.linux` で diagnostic / move / verify 系のログを assert したい時は、必ず `__init__` を caplog コンテキスト内に置く
- VRChat が host で動いていない hermetic 環境前提で `total_candidates=0` を assert すると developer machine で flaky になる。`total_candidates=<digit>` の存在だけ pin し、`matched=[]` / `ambiguous=[]` / `self_pid=<test pid>` で contract を担保する
- 同パターンは [feedback_no_internal_function_mocks](feedback_no_internal_function_mocks.md) の「内部 API を直接呼ぶより public 入口経由で観測する」原則と整合
