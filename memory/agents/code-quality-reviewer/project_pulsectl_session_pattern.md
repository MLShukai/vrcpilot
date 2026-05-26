---
name: pulsectl-session-pattern
description: vrcpilot.mic.linux の _pulse_session(client_name) コンテキストマネージャ。pulsectl の open→close boilerplate を集約する vrcpilot 固有パターン
metadata:
  type: project
---

`vrcpilot.mic.linux._pulse_session(client_name: str) -> Iterator[Any]` は
`open_pulse_control(client_name)` を開き finally で `pulse.close()` を呼ぶ
コンテキストマネージャ。`_runtime_load_null_sink` / `_runtime_unload_null_sink`
の両方で使われている。

**Why:** リファクタ前は両関数が独立に `try: pulse = open_pulse_control(...) except ImportError: ... except Exception: ... try: ... finally: try: pulse.close() except: warning` の同じ shape を持っていた。close failure の
warning ログ文字列もコピペで一致していたので、CM 化が正解だった。

**How to apply:** `pulsectl.Pulse` を扱う新規コードを書く / レビューするとき
は必ずこの CM を経由するよう促す。`speaker/linux.py` にも類似 boilerplate
があるか確認する価値はある（時間があれば横展開候補）。エラー時の戻り値は
caller によって `str | None` だったり `bool` だったりするので、CM は
`open` / `close` だけを集約し、`ImportError` / `Exception` のマッピングは
各関数に残す設計が `_runtime_load_null_sink` / `_runtime_unload_null_sink`
の実装で確立済み。
