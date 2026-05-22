---
name: pyright strict — dict.get on Any-typed dict returns Unknown
description: When narrowing nested untyped JSON via isinstance(x, dict), rebind through dict[Any, Any] before calling .get() to keep return types Any rather than Unknown
type: feedback
---

Under `pyright` strict, calling `.get()` on a dict that was narrowed from `Any` via `isinstance(x, dict)` produces a `reportUnknownMemberType` / `reportUnknownVariableType` error: the narrowed type is `dict[Unknown, Unknown]`, so the return type of the get is also Unknown. This shows up when walking nested JSON like `pw-dump` / OCR config output.

**Why:** Strict mode treats `Unknown` as a hard error, but the narrowing path that turns `Any` into `dict[Unknown, Unknown]` is invisible — `isinstance(x, dict)` looks like it should give you `dict[str, Any]` but doesn't, because `Any` has no key/value type info to propagate.

**How to apply:** After `isinstance(x, dict)`, immediately rebind through an annotated alias and suppress the bind-site warning:

```python
if not isinstance(entry, dict):
    continue
entry_dict: dict[Any, Any] = entry  # pyright: ignore[reportUnknownVariableType]
info: Any = entry_dict.get("info")  # now Any, not Unknown
```

Annotating fields read out of the dict (`media_class: Any = props_dict.get("media.class")`) is also necessary; without the explicit `: Any`, the LHS picks up the propagated `Unknown`.

Concrete instance: `src/vrcpilot/speaker/pipewire.py::PipeWireSpeakerBackend._enumerate_vrchat_nodes` (2026-05-21), walking `pw-dump` JSON across `entry → info → props`.

Related: \[\[feedback_yaml_safe_load_pyright_strict\]\] — same shape for `yaml.safe_load` output.
