---
name: Factory-method seam for COM/native test substitution
description: When a module wraps COM (WGC) or a native extension (proc-tap), encapsulate native init in an overridable factory method and route all native calls through a session struct with lowercase methods so duck-typed fakes can stand in.
metadata:
  type: feedback
---

When wrapping COM (WGC) or other native APIs / extensions in vrcpilot, encapsulate the real native initialisation in a single overridable instance method (e.g. `_open_session(self, ...)` / `_open_capture(self, ...)`) that returns a thin struct/dataclass. The struct exposes lowercase methods (`start`, `stop`, `wait_event`, `close_handle`) which the production path uses uniformly.

**Why:** This factory-method seam lets `tests/fakes/<area>.py`-style duck-typed sessions replace real native objects via `mocker.patch.object(Cls, "_open_session", ...)`. The capture backend at `src/vrcpilot/capture/win32.py` uses this shape for WGC (module-level `WindowsCapture` attribute that tests swap with a `FakeWindowsCapture` subclass). The `speaker/` backend uses the same shape for the `proc-tap` native extension — `_open_capture` returns a `proctap.ProcessAudioCapture` whose lowercase API tests substitute via a `FakeProcessAudioCapture`. Lowercase session methods normalize away COM's CamelCase / vendor naming so the fake never needs to mimic native vtables.

**How to apply:** When implementing a backend that talks to a system API or native extension:

1. Module-level platform guard (`if sys.platform != "win32": raise ImportError` etc.) before other imports, when relevant. Skip when the native extension already does its own platform dispatch (e.g. proc-tap is cross-platform via internal branching).
2. One factory method (`_open_session` / `_open_capture` / etc.) does all the native work and returns a struct.
3. Struct has lowercase wrapper methods around the native verbs.
4. Production `read`/`close` methods touch only the struct's lowercase API.
5. Fake in `tests/fakes/<area>.py` mirrors that exact lowercase surface — no COM vtables, no native handles.

Pyright strict + comtypes (historical note): `comtypes`'s `COMMETHOD` and friends report as `Unknown`. Suppress with `# pyright: ignore[reportUnknownVariableType]` at the import site and rebind through a `typing.Any`-annotated alias so downstream interface declarations don't propagate the unknown type. `comtypes.CoInitializeEx` similarly needs `reportUnknownMemberType` suppression. This was learned while prototyping a WASAPI-direct speaker backend (later replaced by `proc-tap`); no `comtypes`-direct call site currently exists in `src/` (both `capture/win32.py` and `speaker/proctap.py` go through stub-less PyO3/pybind11 extensions, where the analogous fix is `Any`-aliasing the import rather than COM suppression), so revive this recipe only if a future backend pulls `comtypes` back in.
