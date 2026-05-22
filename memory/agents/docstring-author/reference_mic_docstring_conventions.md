---
name: reference-mic-docstring-conventions
description: Recurring docstring patterns observed/established across the vrcpilot mic modality (soundcard + libpulse + WASAPI)
metadata:
  type: reference
---

The mic modality (`vrcpilot.mic.*`, `vrcpilot.cli.mic`,
`vrcpilot.cli.linux_mic`, `tests/fakes/audio.py` soundcard-side fakes,
`tests/e2e/mic.py`) settled on these conventions during Phase 7 of the
soundcard migration. Match them when extending the surface.

- **Backend names**: always spell them as a pair when describing
  failures -- "libpulse / WASAPI" -- so Linux + Windows readers see
  themselves in the same line. Avoid "the native backend" alone.
- **soundcard error surface**: `ImportError` (not installed),
  `OSError` (dlopen failure), `LookupError` (no matching device, raised
  by `get_speaker` / `get_microphone`), `RuntimeError`
  (libpulse/WASAPI runtime errors -- the soundcard fault channel).
  Every public `Mic` / `lookup_speaker` / `_soundcard_visible`
  docstring lists these explicitly.
- **`Speaker.id` vs `Speaker.name` divergence**: the load-bearing fact
  is that PipeWire surfaces the null-sink as
  `id="VRCPilotMic"` / `name="VRCPilot_Virtual_Mic"`. Anything that
  matches by name only misses this. Call it out wherever id-aware
  matching is the bug fix.
- **Mic lifecycle**: "opened at construction, released on close /
  `__exit__` / finaliser". Used in module docstring and class
  docstring; keep wording consistent.
- **`open_pulse_control` seam**: documented as "the single seam every
  caller (`register` / `unregister` / `status`) funnels through, so
  tests patch one symbol". Reuse this phrasing rather than re-deriving
  in each caller.
- **LIBPULSE_HINT**: shared between `cli/linux_mic.py` and
  `cli/mic.py`; both call sites' Raises sections must point to it.
- **Lazy imports**: docstrings for `_run_register` / `_run_unregister`
  / `_run_status` / `_runtime_loaded` use the same ``` # Lazy import: ``vrcpilot.mic.linux`` raises off-Linux. The OS guard in :func: ```run` must short-circuit before reaching here.` comment verbatim.
- **`#:` attribute docstrings**: prefer over docstrings on the
  following line for module-level constants -- matches the rest of the
  codebase (`vrcpilot.mic.base`, `vrcpilot.mic.linux`).

\[\[reference-soundcard-quirks\]\] (in
`memory/agents/spec-driven-implementer/`) is the upstream reference
for soundcard's behaviour itself.
