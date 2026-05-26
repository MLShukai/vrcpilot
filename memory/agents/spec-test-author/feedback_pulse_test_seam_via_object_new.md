---
name: pulse-test-seam-via-object-new
description: pulsectl event loop の制約を避けつつ _module_load_raw のような pulse-touching test seam を実 daemon でテストするには object.__new__ で __init__ をスキップして手動で _pulse を立てる
metadata:
  type: feedback
---

`PipeWireSpeakerBackend._module_load_raw` のような **pulsectl の sync API を呼ぶ test seam** を実 daemon でテストしたい時、full `__init__` を回した後にメインスレッドから seam を呼ぶと、event listener thread が走っているせいで pulsectl が `PulseLoopStop` で blocking 拒否する (\[\[caplog-around-pulsectl-backend-constructor-not-internal-methods\]\] と同じ問題)。

**対処**: `object.__new__(PipeWireSpeakerBackend)` で `__init__` をスキップして minimal instance を作り、`backend._pulse = pulsectl.Pulse("test-name")` を **手動で** 立てる。この Pulse には event listener thread が無いので sync API を main thread から呼べる。3rd-party モックではなく **実 Pulse** を使うので project policy にも整合する。

```python
backend: PipeWireSpeakerBackend = object.__new__(PipeWireSpeakerBackend)
backend._pulse = pulsectl.Pulse("vrcpilot-test-seam-XYZ")
idx: object = None
try:
    idx = backend._module_load_raw("module-null-sink", args)
    assert isinstance(idx, int)
finally:
    if isinstance(idx, int):
        try:
            backend._pulse.module_unload(idx)
        except Exception:
            pass
    try:
        backend._pulse.close()
    except Exception:
        pass
```

**Why:**

- pulsectl は同じ Pulse connection 上で event listener thread と sync API を並行で叩けない仕様 (3rd-party の制約)
- `_module_load_raw` のような薄ラッパー seam を **delegate であることだけ** 確認したい場合、full backend の event loop は冗長
- `mocker.patch.object` で `pulse.module_load` を mock するのは 3rd-party 表面のモックになり禁止
- 一方、**retry ロジック自体** (`_load_module`) の test では full backend を構築した後に `mocker.patch.object(backend, "_module_load_raw", side_effect=[...])` で seam を差し替える。patched seam は pulsectl に触らないので event loop race は起きない

**How to apply:**

- pulse-touching な薄ラッパー seam の "delegate であること" のテスト → `object.__new__` パターンで実 Pulse を attach
- seam を経由する上位ロジック (retry / validation / dispatch) のテスト → full backend 構築 + `mocker.patch.object(backend, "<seam>", side_effect=[...])`
- 共通: `_pulse.close()` は必ず finally で呼ぶ (Pulse は最低限 close しないと daemon にゾンビ client が残る)
