---
name: yaml.safe_load returns Unknown under pyright strict
description: Coercing yaml.safe_load values via int()/str() trips reportUnknownArgumentType; cast the dict after isinstance narrow
type: feedback
---

After `payload = yaml.safe_load(text)` and `if not isinstance(payload, dict):`, pyright strict still narrows the dict to `dict[Unknown, Unknown]`. Subsequent `int(payload["x"])` / `str(payload["path"])` calls then fail with `reportUnknownArgumentType` even though they are intended runtime coercions.

**Why:** `yaml.safe_load` is typed as returning `Any`, but `isinstance(obj, dict)` only narrows the outer container type. The element type stays `Unknown` under strict, and `int()` / `str()` reject Unknown arguments under `reportUnknownArgumentType`.

**How to apply:** Right after the `isinstance` check, do `payload = cast(dict[str, Any], raw)` (import `cast` and `Any` from `typing`). The runtime safety is provided by the surrounding `try / except (KeyError, TypeError, ValueError)` block — the cast is purely to satisfy the type checker. Add a brief comment explaining the cast so reviewers do not flag it as a lint smell. Pattern is established in `src/vrcpilot/screenshot.py::Screenshot.load`.
