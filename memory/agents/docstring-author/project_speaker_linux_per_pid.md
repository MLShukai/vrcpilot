---
name: project-speaker-linux-per-pid
description: vrcpilot.speaker.linux per-PID PipeWire backend docstring patterns — routing replacement vs addition, LIFO teardown rationale, trailing-space anchor rationale, ExitStack callback-name preservation
metadata:
  type: project
---

`src/vrcpilot/speaker/linux.py` was rewritten from a single shared
`vrcpilot_tap` sink to a per-PID null-sink + `module-loopback` +
`sink_input_move` design. Polishing docstrings here requires
foregrounding several non-obvious design rationales that *cannot* be
inferred from the code alone:

**Module-level rationales worth preserving on every pass:**

- **Routing replacement, not addition.** `Pulse.sink_input_move`
  *replaces* the input's routing rather than adding a link. The
  module-loopback is then the *only* path back to the speakers. This
  is the load-bearing difference from the old design that leaked
  audio between concurrent instances; mention it on
  `_move_existing_streams_to_tap` and in the module docstring's
  dedicated section.
- **LIFO teardown order.** Loopback unloads *before* null-sink in
  both `_reset_stale_taps` and `close()` so a live loopback never
  observes a deleted source mid-pull. State file removal comes after
  the modules so a concurrent janitor never sees a breadcrumb
  without its sink.
- **`create_time` mismatch = PID reuse.** PIDs are kernel-recycled;
  the `vrchat_create_time` stamp in the state file is what
  distinguishes "this tap belongs to the still-living VRChat we
  expect" from "the original VRChat crashed and an unrelated process
  inherited its PID". Document on the module header and
  `_reset_stale_taps`.

**Trailing-`\s` regex anchor:**

`_NULL_SINK_RE` / `_LOOPBACK_RE` end with `\s` and
`_extract_tap_pid` appends a trailing space to the needle before
matching. Without that anchor, `vrcpilot_tap_1234` would spuriously
match `vrcpilot_tap_12345`, so the stale-tap sweep would unload an
unrelated, live PID's sink. Pin this rationale on
`_extract_tap_pid`; keep the constants' docstrings to a
cross-reference rather than duplicating the explanation.

**Thin `_safe_unload_loopback` / `_safe_unload_null_sink` delegators:**

These exist as wrappers around `_safe_unload_by_attr` (a single
shared body) *because* `ExitStack.callback` and traceback frames
render the callable's `__name__`. A frame labelled
`_safe_unload_loopback` is far more debuggable from a
partial-teardown log than a generic `_safe_unload_by_attr`. Document
this rationale on `_safe_unload_by_attr`; the per-method docstrings
can stay one-line.

**Test seams (`_open_pulse`, `_spawn_pw_record`):**

These exist as overridable methods so tests can substitute
stand-ins via `mocker.patch.object` *without* mocking `pulsectl` or
`subprocess` directly — the project's testing policy forbids
faking 3rd-party surfaces. Call this out in their docstrings;
otherwise reviewers will inline them.

**See also:**

- \[\[project-speaker-subpackage\]\] for the broader `vrcpilot.speaker`
  conventions (PID isolation as the load-bearing intent, drain-all
  read contract, lazy backend dispatch).
- \[\[project-capture-backend-lifecycle\]\] for the parallel ExitStack /
  never-raises-close pattern in `vrcpilot.capture`.
