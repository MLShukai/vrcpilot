---
name: project-speaker-subpackage
description: vrcpilot.speaker docstring conventions — PID-isolated capture intent, lazy backend dispatch rationale, drain-all read contract
metadata:
  type: project
---

`vrcpilot.speaker` captures **VRChat-only** audio: process isolation
(Windows proc-tap binds the WASAPI Process Loopback to one PID; Linux
PipeWire filters output nodes by `application.process.id`) is the
load-bearing differentiator vs `mic/` which is a recording surface.
Docstrings on `Speaker` / backend classes should lead with that
isolation intent rather than "captures audio".

- **`_select_speaker_backend` lazy imports**: the platform-specific
  submodules (`speaker/linux.py`, `speaker/windows.py`) each raise
  `ImportError` at import time on the wrong platform (`pulsectl`
  available only on Linux; `proc-tap` gated to `sys_platform == 'win32'`
  in `pyproject.toml`). The factory imports them inline so a top-level
  import would crash collection on cross-platform CI shards. Always
  document this rationale on the dispatch helper — it is the only
  reason the inline-import pattern exists and reviewers may "fix" it
  otherwise.
- **`read_timeout` unit narration**: spelled out once in the
  `Args:` block of each backend / wrapper. Do not also restate "in
  seconds" in the summary paragraph (caught by the user in this
  subsystem's review).
- **`read()` shape contract**: `(N, CHANNELS)` ndarray; empty
  `(0, CHANNELS)` is the documented "no new audio within
  `read_timeout`" tick, not an error. Pin this verbatim on every
  override and on the ABC because consumer pipelines (sinks, VAD)
  decide silence vs error on the shape, not on a thrown exception.
- **Drain-all read pattern**: both `ProcTapSpeakerBackend.read` and
  `PipeWireSpeakerBackend.read` block up to `read_timeout` for the
  first chunk and then non-blocking drain everything that piled up
  since the previous call (one `read` hand-off covers the full buffer).
  Document this as a non-obvious behavioural contract on the read path,
  not just an implementation detail — it is the reason the wrapper can
  run the loop with `chunk_seconds=0.05` without dropping audio.
- **`SpeakerLoop` exception-stashing contract**: worker-thread
  exceptions are stashed and re-raised on the next `stop()` / `close()`.
  Document this on the class docstring (silent thread death detection)
  and reinforce in `stop()` (one-shot surfacing, cleared after raise).

Related: \[\[project-capture-backend-lifecycle\]\] for the parallel
ExitStack / never-raises-close / lazy-dispatch patterns in
`vrcpilot.capture`. \[\[reference-mic-docstring-conventions\]\] for the
sibling mic surface's lazy-import comment template — speaker's
`_select_speaker_backend` uses the same intent (avoid loading the
opposite-platform optional dep) but phrased per backend rather than
once globally.
