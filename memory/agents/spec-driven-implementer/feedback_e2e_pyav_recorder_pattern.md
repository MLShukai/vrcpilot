---
name: e2e-pyav-recorder-pattern
description: Use small e2e-local PyAV recorder helpers (tests/e2e/_pyav_recorder.py) instead of importing CLI-internal muxers; keeps e2e CLI-independent and works as a Python-API usage example
metadata:
  type: feedback
---

When the e2e suite needs to write video/audio captured from
`CaptureLoop` / `SpeakerLoop` into a file, put a minimal PyAV-backed
recorder in `tests/e2e/_pyav_recorder.py` and call it from the
scenario — do **not** import `vrcpilot.cli.record.muxer`.

**Why:** Per user direction (2026-05-22, `refactor/20260522/unify-record-pyav`),
e2e scenarios are intended to read like a Python-API user's
program. The CLI's muxer is intentionally absent from any
`__all__` and is treated as private — importing it would couple e2e
tests to an internal contract that may change. Replicating the
recipe locally (single-stream, no thread lock, no mid-stream
validation) keeps the scenarios stable and doubles as a worked
example for downstream users.

**How to apply:**

- The helper module's filename starts with `_` so
  `tests/e2e/all.py::_discover()` skips it.
- The classes inside should **not** start with `_`. The leading-`_`
  on the module is what marks the module private; if class names
  also have `_`, pyright fires `reportPrivateUsage` warnings on
  every cross-module reference. Names like `Mp4VideoRecorder` /
  `WavAudioRecorder` are fine.
- Constants like `_SAMPLE_RATE: int = 48000` and `_CHANNELS: int = 2`
  can mirror `vrcpilot.speaker.base` without importing from
  package-private modules.
- `add_stream("libx264", rate=...)` / `add_stream("pcm_s16le", ...)`
  returns a partially-unknown overload under pyright strict; rebind
  through an annotated local and silence with
  `# pyright: ignore[reportUnknownMemberType]` exactly like the CLI
  muxer does.
- `pyproject.toml` `[tool.pyright].exclude` can stay clear of
  `tests/e2e/` so the helpers and scenarios are kept honest under
  default (non-strict) pyright; the package strict block is still
  scoped to `./src/`.

Concrete instance: commit `83eae22` "test(e2e): e2e シナリオを Python
API + 自前 PyAV recorder に書き換え（CLI 非依存）", which rewrote
`tests/e2e/capture.py` and `tests/e2e/speaker.py` against
`tests/e2e/_pyav_recorder.py` after the old `Mp4FrameSink` /
`WavFileSink` were removed in commit `9c6105d`.
