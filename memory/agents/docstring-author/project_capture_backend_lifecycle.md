---
name: vrcpilot capture backend lifecycle docstring patterns
description: Recurring intent-bearing facts about CaptureBackend implementations that public docs must preserve (synchronicity, close-race semantics, never-raises contract, no-unredirect rationale)
metadata:
  type: project
---

The two `CaptureBackend` implementations (`Win32CaptureBackend`,
`X11CaptureBackend`) share an ABC but diverge on several non-obvious
points that callers and future implementers need spelled out in
docstrings, not narrated as code-behavior:

- **Synchronicity asymmetry**: Win32 (WGC) `read()` *blocks* on a
  `threading.Event` set by a free-threaded callback; X11 `read()` is
  *synchronous* — it re-grabs the off-screen pixmap each call via
  Composite. The public `Capture.read` Raises block already calls out
  that `TimeoutError` is "Windows / WGC only", so backend-level docs
  should reinforce this with the *why* (no producer thread on X11 ⇒
  nothing to race with ⇒ no timeout needed).
- **Close race (Windows only)**: `Win32CaptureBackend.close` sets
  `_frame_event` to wake any thread blocked in `read`. The post-wait
  `if self._closed:` re-check is the load-bearing invariant — without
  it `read` could return a stale frame after shutdown. Document this
  as the *reason* a `RuntimeError` (not `TimeoutError`) is raised when
  the closed flag flipped during the wait.
- **`close()` never-raises contract**: Both backends downgrade
  cleanup failures (`Xlib.display.close`, `CaptureControl.stop`) to
  `RuntimeWarning`. This is contract, not defensive coding — `Capture`
  relies on it so `__exit__` paths are safe. Always cite this in
  backend `close` docstrings.
- **No-unredirect on X11**: `X11CaptureBackend.close` only closes the
  display connection; the Composite redirect is per-client and the
  server drops it on disconnect. An explicit `unredirect_window` would
  risk an XError on a window that may have already gone away. Worth
  documenting because it looks like a missing cleanup at first glance.

**Why:** These are all "why does this code look this way" notes —
exactly what docstrings should carry and what code comments tend to
miss. They are stable design decisions, not implementation trivia.

**How to apply:** When editing `capture/base.py`, `capture/linux.py`,
or `capture/windows.py`, keep these four points reflected in the
corresponding docstrings. If the implementation changes (e.g. WGC
gains a synchronous mode, or X11 starts using XComposite NameWindow
notifications), revisit this memory.

Related: \[\[vrcpilot-capture-vs-screenshot-api-split\]\] for the
broader streaming-vs-one-shot rationale.
