---
name: ExitStack for partial-init resource unwind in long __init__
description: Use contextlib.ExitStack to register rollback callbacks after each acquisition step; pop_all() on success — replaces nested try/except in multi-step backend constructors
type: feedback
---

When a backend constructor acquires N resources in sequence (e.g. `PipeWireSpeakerBackend` opens a pulsectl session, loads a null-sink, writes a state file, spawns a subprocess, starts two threads), express the partial-init unwind with `contextlib.ExitStack` rather than nested `try/except` pyramids.

**Why:** A nested try/except for 7 acquisitions becomes a 7-deep pyramid that is hard to read and trivially miss-orders cleanup. ExitStack pushes rollback callbacks in acquisition order and unwinds them in reverse order — same semantics as the pyramid but linear in source. On success the constructor calls `stack.pop_all()` to commit (so cleanup runs in `close()`, not when the stack falls out of scope). Each rollback callback (`_safe_close_pulse`, `_safe_unload_null_sink`, etc.) is `try`-wrapped and warns-on-failure, so a misbehaving cleanup step doesn't abort the unwind.

**How to apply:**

```python
stack = ExitStack()
try:
    self._a = self._acquire_a()
    stack.callback(self._safe_release_a)

    self._b = self._acquire_b()
    stack.callback(self._safe_release_b)

    # ... more steps ...
except BaseException:
    stack.close()  # runs all registered callbacks in LIFO order
    raise

stack.pop_all()  # success: keep resources, cleanup moves to close()
```

The `_safe_release_*` methods are then reused by `close()` itself in the same reverse order. This collapses the test surface: one test "partial init raises after step N" verifies the chain unwinds correctly for every prefix, and the same `_safe_release_*` helpers are exercised by both paths.

Concrete instance: `src/vrcpilot/speaker/pipewire.py` (PipeWireSpeakerBackend, 2026-05-21). Test `test_cleanup_on_partial_startup_failure` plants a failure in `_spawn_pw_record` and asserts both `pulse.module_unload_calls` and state-file deletion happened.

Related: \[\[feedback_factory_seam_pattern\]\] — the `_acquire_*` methods double as test seams for `mocker.patch.object` substitution.
