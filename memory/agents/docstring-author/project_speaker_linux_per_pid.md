---
name: project-speaker-linux-per-pid
description: vrcpilot.speaker.linux per-PID PipeWire backend docstring patterns — two-stage explicit global-port-id pw-link routing, object.id vs object.serial trap, pw-dump tempfile race, --target=0 capture side, port-link diagnostic contract, teardown order, regex anchor, ExitStack callback-name preservation
metadata:
  type: project
---

`src/vrcpilot/speaker/linux.py` isolates each VRChat process's audio onto
its own `vrcpilot_tap_{pid}` `module-null-sink`. The routing was rebuilt
(Phase B v2, 2026-05) from the earlier `Pulse.sink_input_move` approach to
**two explicit `pw-link` hops made by global PipeWire port id**, after the
old design produced bit-identical silence on real hardware. Real-hardware
e2e now confirms per-PID separation (two concurrent VRChat instances yield
distinct, non-silent, uncorrelated recordings). Polishing docstrings here
requires foregrounding several non-obvious rationales that *cannot* be
inferred from the code alone.

**The earlier design and why it failed (keep this WHY, it is the whole point):**

The previous design moved the stream with `Pulse.sink_input_move`
(`target.object` metadata via the Pulse-compat layer). Two Wireplumber
session-policy behaviours silently broke it, and **both** are worth keeping
in the module header as the reason for the current shape:

- `sink_input_move` (= `target.object` metadata) is reverted by session
  policy (`stream-restore` / `follow-default-target`) *after* the API call
  returns success — the API lies at its boundary.
- `pw-record --target=<sink>.monitor` is redirected to the *default* sink's
  monitor by the session manager when more than one sink exists. This is
  the literal cause of the "two backends both record bit-identical silence"
  symptom.

User-created explicit `pw-link` port links are **not** subject to that
policy, which is why the current design wires everything by hand. Do not
let a future doc "simplify" back toward `sink_input_move` or a name- /
sink-targeted `pw-record` — that re-introduces the silence.

**Two-stage explicit global-port-id linking (the current routing, per pid):**

1. *producer → tap*: VRChat `sink_input` output ports are linked onto the
   per-pid `vrcpilot_tap_{pid}` null-sink's playback ports
   (`_link_existing_vrchat_nodes_to_tap`). This is **additive** — the
   stream's existing link to the default sink is left in place, so **the
   user keeps hearing VRChat through the default speakers while recording.**
   (Document this UX fact; a reader who assumes "moving" routing will think
   recording mutes VRChat, which is now false.)
2. *tap monitor → recorder*: the tap's monitor ports are linked onto a
   `pw-record` subprocess spawned with `--target=0`
   (`_link_tap_monitor_to_record`).

**Why global *port* id, not node id and not port name** (load-bearing on the
module header and on `_pw_link_ports` / `_link_ports_between_nodes`):

- Two concurrent VRChat instances share the node name `VRChat.exe`, so a
  **name**-based `pw-link` (port-name form `VRChat.exe:output_FL`) always
  resolves the same producer and silently cross-wires the taps — unusable.
- The **node-id** `pw-link` form returns a non-zero exit code even on
  success, so it cannot drive returncode branching.
- **Global port ids are unique per port**, so each hop links exactly the
  intended ports. They are resolved from `pw-dump` (the only source that
  maps a node id to its ports under a name collision).

**`object.id` vs `object.serial` (the subtle trap — pin on `_resolve_vrchat_node_ids`):**

A VRChat `sink_input` proplist carries both. **`object.id` is the PipeWire
node's global id** — it equals the `pw-dump` Node top-level `id` and the
Ports' `node.id`, so it is the identifier returned and used to key the
port lookup. **`object.serial` is a *different* value that does not map to
`pw-dump` node ids**; it is logged as `node_serial` for diagnostics only.
A doc (or a refactor) that conflates them or "prefers serial" silently
makes the port lookup miss every node. Keep both fields named in the
candidate-log schema but make clear only `object.id` drives linking.

**`--target=0` on the capture side (pin on `_pw_record_argv` / `_spawn_pw_record`):**

`pw-record` is spawned with `--target=0` to **disable auto-connect** so its
input ports stay free for the explicit capture-side link. A name- or
sink-targeted recorder would be redirected to the default sink's monitor by
the session manager (see the failure above), capturing the wrong audio or
silence. The recorder's free input ports are then wired from the tap's
monitor ports by global port id.

**Unique `pw-record` node.name (pin on `_record_node_name`):**

`pw-record` does **not** expose `application.process.id` in its PipeWire
props, so the recorder cannot be located by OS pid. It is spawned with a
unique `node.name` (`vrcpilot_rec_{pid}`, via `pw-record -P`) so two
concurrent backends never clash; `_link_tap_monitor_to_record` /
`_wait_for_record_node` find the recorder node in `pw-dump` by that name.
A plain shared name would let the capture-side link attach to the wrong
recorder.

**`pw-dump` via tempfile, not pipe (pin on `_pw_dump_raw`):**

`pw-dump` output is written to a temp file and read back rather than
captured straight off the pipe. Piping `pw-dump` directly is racy under
daemon contention — it intermittently returns an empty or truncated
payload — whereas redirecting to a file yields the complete dump. The
pure-parse helpers (`_parse_pw_dump`, `_find_node_id_by_name`,
`_find_ports`) all degrade to "no match" (empty list / `None`) rather than
raising, so a transient bad dump never aborts start-up; document that
degradation intent rather than the parsing mechanics.

**`create_time` mismatch = PID reuse (unchanged from before — keep it):**

PIDs are kernel-recycled; the `vrchat_create_time` stamp in the state file
is what distinguishes "this tap belongs to the still-living VRChat we
expect" from "the original VRChat crashed and an unrelated process
inherited its PID". Document on the module header and `_reset_stale_taps`.

**Diagnostic contract (port-link based):**

The backend's correctness is only verifiable from its log stream, because
PipeWire-Pulse can lie at the API boundary. The multi-instance e2e captures
and tests grep on these prefixes, so they must not be renamed casually:

- `_resolve_vrchat_node_ids` emits one `sink_input candidate | ...` INFO
  line per VRChat-like candidate (carrying `node_serial` /
  `node_object_id` / `node_name`) and ends with a `sink_input scan summary | ...` line. Document the schema only at the contract level
  (don't enumerate every field) — the schema lives in the code and the log.
- `_pw_link_ports` logs each link outcome keyed by global port ids:
  `port link ok` (returncode 0), `port link already present` (non-zero with
  `File exists` stderr — the idempotent re-link case, e.g. from the event
  listener), or `port link failed` (any other non-zero). It also forwards
  `pw-link`'s own stderr under `pw-link stderr | ...`. `_link_ports_between_nodes`
  ends with one `port link summary | ...` line per node pair. There is **no
  `sink_input_move post-verify`** in this design — the analogue is the
  port-link ok/already-present/failed + summary lines.
- `_on_pulse_event` emits one `on_pulse_event | ...` line per event so a
  post-mortem can confirm the listener actually fired (a silent data plane
  while the listener never woke is a distinct failure mode).
- `_drain_stderr` forwards every `pw-record` stderr line under
  `pw-record stderr | ...` at INFO. The *why*: the `--target=0` recorder
  can still emit ALSA / PipeWire connection errors and xruns whose only
  signal is one stderr line.

**Teardown order (`close()`):**

There is no loopback and no explicit unlink. Links garbage-collect when the
nodes/sink are destroyed. Current order:

1. event listener (so it can't fire a callback into a half-torn-down backend)
2. `pw-record` terminate (lets both drain threads observe EOF)
3. stdout drain join, then stderr drain join (`pw-record` closes stderr
   after stdout — `_safe_join_drain_err_thread` has *no* dedicated stop flag
   and relies on this ordering; document it on that method's docstring)
4. null-sink unload — removing the tap's ports lets PipeWire
   garbage-collect every `pw-link` the backend created, so no explicit
   unlink is needed. VRChat's own link to the default sink was never
   touched, so the user keeps hearing it throughout.
5. state file (after the module, so a concurrent janitor never sees a
   breadcrumb without its sink)
6. pulse control connection last

When updating older docs that mention "auto-reroute back to default" or
"loopback unload", excise them — there is no move to reroute and no
loopback; links simply GC with the destroyed tap.

**Trailing-`\s` regex anchor (unchanged):**

`_NULL_SINK_RE` ends with `\s` and `_extract_tap_pid` appends a trailing
space to the needle before matching. Without that anchor,
`vrcpilot_tap_1234` would spuriously match `vrcpilot_tap_12345`, so the
stale-tap sweep would unload an unrelated, live PID's sink. Pin this
rationale on `_extract_tap_pid`; keep the constant's docstring to a
cross-reference rather than duplicating the explanation. (There is no
`_LOOPBACK_RE` — the loopback is gone.)

**Test seams (`_open_pulse`, `_spawn_pw_record`, `_pw_link_run_raw`, `_pw_dump_raw`, `_module_load_raw`):**

These exist as overridable methods so tests can substitute stand-ins via
`mocker.patch.object` *without* mocking `pulsectl` or `subprocess` directly
— the project's testing policy forbids faking 3rd-party surfaces. Each is a
single-call factory whose per-call outcome a test feeds via `side_effect`.
Call this out in their docstrings; otherwise reviewers will inline them.
(`_safe_unload_null_sink` is now a standalone named method — not a thin
delegate to a shared `_safe_unload_by_attr` — kept named so `ExitStack.callback`
and traceback frames render a debuggable `__name__`.)

**See also:**

- \[\[project-speaker-subpackage\]\] for the broader `vrcpilot.speaker`
  conventions (PID isolation as the load-bearing intent, drain-all
  read contract, lazy backend dispatch).
- \[\[project-capture-backend-lifecycle\]\] for the parallel ExitStack /
  never-raises-close pattern in `vrcpilot.capture`.
- \[\[project-tests-e2e-docstring-style\]\] — the multi-instance
  scenario uses MD5 + Pearson correlation as the isolation
  assertion contract.
