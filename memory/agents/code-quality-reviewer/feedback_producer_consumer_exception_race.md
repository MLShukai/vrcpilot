---
name: producer/consumer exception planted under same lock as notify
description: when a background producer queues an exception for the consumer to surface, the planting write MUST happen inside the same condition the consumer waits on
metadata:
  type: feedback
---

When a background thread (drain / listener) stashes an exception that
the next consumer call should re-raise, both producer and consumer
must touch the exception slot under the same `threading.Condition`
they use to coordinate the data buffer. The "check, then wait" idiom
without the lock is a real race, not a theoretical one.

**Why:** The natural shape is producer writes `self._exc = ...`, then
`notify_all()` under the condition; consumer checks `self._exc` first
(early-out), then takes the condition and `wait()`s for data. If the
producer's notify lands in the gap between the consumer's `_exc` read
and its `wait()`, the consumer wakes from `wait()` thinking it's a
normal data notify, finds an empty buffer, and returns `(0, channels)`
or whatever the empty-payload signal is — silently dropping the
exception. Found in `src/vrcpilot/speaker/pipewire.py` 2026-05-21:
`read()` checked `_stdout_exception` before entering
`_stdout_condition`, and the drain thread wrote `_stdout_exception`
outside the condition before calling `notify_all()` under it.

**How to apply:** When reviewing producer/consumer queues that
multiplex "data ready" and "error to surface" on one condition:

1. Read every write site of the exception slot. If any of them is
   outside the condition, that's a should-fix or critical (depending
   on whether `read()` early-outs on the slot).
2. Read the consumer. If it checks the exception slot before taking
   the condition, that's the race — move the check **inside** the
   condition, and re-check after `wait()` returns so a planted
   exception delivered concurrently with the wait is observed.
3. Tests that plant the exception slot directly (a common test
   pattern for `_stdout_exception` / `_exc` slots) should acquire
   the condition while writing, mirroring the production invariant.

Concrete fix shape (consumer):

```python
with self._cond:
    exc = self._exc
    if exc is None and not self._buf:
        self._cond.wait(timeout=self._timeout)
        exc = self._exc  # re-check after wakeup
    if exc is not None:
        self._exc = None
        raise WrappedError(...) from exc
    chunk = bytes(self._buf)
    self._buf.clear()
```

The "check twice, raise once" shape is the canonical fix; alternatives
(splitting data and error onto separate conditions, polling with a
short timeout) trade simplicity for marginal CPU savings.
