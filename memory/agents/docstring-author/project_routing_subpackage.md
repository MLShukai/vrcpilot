---
name: project-routing-subpackage
description: vrcpilot.speaker.routing docstring conventions — relay lifecycle, 3-stage device resolution, error hierarchy, record-vs-routing distinction
metadata:
  type: project
---

`vrcpilot.speaker.routing` is the **output** half of the speaker
subsystem (counterpart to `vrcpilot.speaker`'s capture half). It pairs
the existing PID-scoped `SpeakerLoop` capture with a :mod:`soundcard`
output player to relay one VRChat process's audio to a chosen device.
Cross-platform: no Windows / Linux split inside `routing/` itself
because both `soundcard` (output) and `Speaker` (capture) already
abstract their platforms. See
`memory/specs/pid_speaker_routing_relay.md` for the full contract.

Recurring docstring points that must stay reflected when editing:

- **Record vs route confusion**: name the distinction on the package
  `__init__` so readers do not conflate the two. `vrcpilot record`
  writes capture frames to a *file*; routing forwards them to an
  *output device*. Same capture source, different sinks.
- **`Router` lifecycle is the load-bearing surface**: construction
  resolves the device but opens *nothing*; `start()` opens the player
  first, then `SpeakerLoop`, with rollback on capture-side failure;
  `stop()` cleans the player in `finally` so a worker-raised exception
  never leaks the output stream. Double-`start()` / double-`stop()`
  are intentional no-ops (F2.3 / F2.5). Re-start after stop is
  supported (F2.13) — fresh `SpeakerLoop` and player are created — so
  re-entering the `with` block is well-defined. All of this lives in
  the class docstring, not narrated in `start()` / `stop()` only.
- **`__exit__` never swallows**: explicitly note the `None` return
  (not `False`) keeps body exceptions propagating. A worker exception
  re-raised from `stop()` replaces the body exception via standard
  `__exit__` chaining — say so rather than letting readers infer it.
- **Threading note**: `start` / `stop` are main-thread; `_on_frames`
  runs on the worker thread and uses a single-snapshot read of
  `_sc_player` (no lock) — this is *why* there is no mutex around
  the relay path. Document on the class, reinforce on `_on_frames`.
- **`find_device` 3-stage resolution**: id-exact → name-exact
  (case-sensitive) → name-substring (case-insensitive). The
  no-fallthrough rule on ≥2 candidates is the surprising bit: an
  ambiguous match at *any* stage raises `AudioRoutingError`
  immediately, it does not retry the next stage. Always state both
  the stage order and the no-fallthrough rule.
- **`AudioDevice.id` is opaque**: callers should treat it as a black
  box — Windows endpoint GUID, Linux PipeWire node identifier — and
  only feed it back into `find_device` / `Router`. Worth a sentence
  because the type is just `str` and the name `id` invites
  speculation about format.
- **Error hierarchy**: `DeviceNotFoundError <: AudioRoutingError <: RuntimeError`. Direct `AudioRoutingError` instances are
  ambiguity-only (multi-hit); zero-hit raises the subclass. Mention
  on both classes so either entry point in the API docs makes the
  relationship visible.
- **Cross-link to `docs/virtual-audio.md`**: the user-facing routing
  playbook lives there. Link from the module `__init__` so readers
  navigating from `help(vrcpilot.speaker.routing)` find it.
- **`route()` is a one-call convenience**: emphasise that the caller
  owns the lifecycle of the returned `Router`. On `start()` failure no
  router is returned (the rollback inside `Router.start` already
  released the partial player) — explicit because the obvious mental
  model "I got a half-open object I need to clean up" is wrong.

Related: \[\[project-speaker-subpackage\]\] for the capture half
(PID-isolation intent, `SpeakerLoop` exception-stashing contract that
`Router.stop()` propagates through). \[\[reference-mic-docstring-conventions\]\]
for the sibling soundcard-using surface (mic), which uses the same
`ImportError` / `OSError` / `LookupError` / `RuntimeError` error
vocabulary — keep the wording aligned.
