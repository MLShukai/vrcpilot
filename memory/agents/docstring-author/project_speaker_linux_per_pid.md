---
name: project-speaker-linux-per-pid
description: vrcpilot.speaker.linux per-PID PipeWire backend docstring patterns — null-sink-only routing, diagnostic contract (candidate log + move post-verify + pw-record stderr drain), teardown order, regex anchor, ExitStack callback-name preservation
metadata:
  type: project
---

`src/vrcpilot/speaker/linux.py` was rewritten from a single shared
`vrcpilot_tap` sink to a per-PID null-sink + `sink_input_move` design.
Phase A (2026-05) of the per-PID isolation fix **removed** the
`module-loopback` from tap monitor back to the default sink that the
earlier design carried — the loopback was the load-bearing leak that
broke isolation when two VRChat instances were captured concurrently.
Polishing docstrings here requires foregrounding several non-obvious
design rationales that *cannot* be inferred from the code alone:

**Module-level rationales worth preserving on every pass:**

- **No monitor bridge by design.** The backend deliberately does
  not load a `module-loopback`. Documenting this is load-bearing
  because the next reader will wonder why the user can't hear VRChat
  during recording and want to "fix" it by adding one back. Flag the
  UX trade-off explicitly: *isolation correctness is the reason*.
  Recovery happens at `close()` time via PulseAudio's automatic
  reroute when the null-sink disappears — no explicit move-back is
  needed.
- **Routing replacement, not addition.** `Pulse.sink_input_move`
  *replaces* the input's routing rather than adding a link. Mention
  this both on the module header and on
  `_move_existing_streams_to_tap` — it is the design's only path,
  so a regression that tries to "also keep the original sink" would
  re-introduce the leak Phase A removed.
- **`create_time` mismatch = PID reuse.** PIDs are kernel-recycled;
  the `vrchat_create_time` stamp in the state file is what
  distinguishes "this tap belongs to the still-living VRChat we
  expect" from "the original VRChat crashed and an unrelated process
  inherited its PID". Document on the module header and
  `_reset_stale_taps`.

**Diagnostic contract (Phase A):**

The backend's correctness is only verifiable from its log stream,
because PipeWire-Pulse can lie at the API boundary. Three pieces
together form the contract; e2e captures and tests grep on these
prefixes, so they must not be renamed casually:

- `_enumerate_vrchat_sink_inputs` emits one
  `sink_input candidate | ...` INFO line per VRChat-like candidate
  and ends with a `sink_input scan summary | ...` line. Document
  the schema only at the contract level (don't enumerate every
  field in the docstring) — the schema sits in the code and the
  log itself.
- `_verify_sink_input_moved` emits
  `sink_input_move post-verify ok | ...` /
  `... post-verify failed | ...` / `... post-verify query failed | ...`.
  The *why* this exists is critical and must stay in the docstring:
  `pulsectl.sink_input_move` can return success while the underlying
  PipeWire-Pulse layer leaves the route on a different sink
  (auto-routing policies, `stream.target` hints, session-manager
  policy). Without the re-query the only symptom is "the recording
  is empty even though startup logged success".
- `_drain_stderr` forwards every `pw-record` stderr line under the
  `pw-record stderr | ...` prefix at INFO. The *why*: `pw-record`
  silently falls back to a different source node when its
  `--target=...` can't be resolved, and the only signal is one
  stderr line. Without this drain the backend would produce audio
  from the wrong sink with no visible error.

**Teardown order (post-Phase A):**

The loopback unload step is gone. Current `close()` order:

1. event listener (so it can't fire into a half-torn-down backend)
2. `pw-record` terminate (lets both drain threads observe EOF)
3. stdout drain join, then stderr drain join (`pw-record` closes
   stderr after stdout — `_safe_join_drain_err_thread` has *no*
   dedicated stop flag and relies on this ordering; document it on
   that method's docstring)
4. null-sink unload — disappearing this triggers PulseAudio's
   auto-reroute of VRChat's `sink_input` back to the default sink
5. state file (after the module, so a concurrent janitor never
   sees a breadcrumb without its sink)
6. pulse control connection last

When updating older docs that mention "loopback unloads before
null-sink", excise the loopback step rather than reordering — it
is gone.

**Trailing-`\s` regex anchor:**

`_NULL_SINK_RE` ends with `\s` and `_extract_tap_pid` appends a
trailing space to the needle before matching. Without that anchor,
`vrcpilot_tap_1234` would spuriously match `vrcpilot_tap_12345`, so
the stale-tap sweep would unload an unrelated, live PID's sink.
Pin this rationale on `_extract_tap_pid`; keep the constant's
docstring to a cross-reference rather than duplicating the
explanation. (The old `_LOOPBACK_RE` is gone with the loopback.)

**Thin `_safe_unload_null_sink` delegator:**

Exists as a wrapper around `_safe_unload_by_attr` (a single
shared body) *because* `ExitStack.callback` and traceback frames
render the callable's `__name__`. A frame labelled
`_safe_unload_null_sink` is far more debuggable from a
partial-teardown log than a generic `_safe_unload_by_attr`.
Document this rationale on `_safe_unload_by_attr`; the wrapper's
docstring can stay one-line. (Phase A also removed
`_safe_unload_loopback` — only the null-sink wrapper remains.)

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
- \[\[project-tests-e2e-docstring-style\]\] — the multi-instance
  scenario uses MD5 + Pearson correlation as the isolation
  assertion contract (Phase A elevated this from "Observation, not
  threshold assertion" to a real PASS criterion).
