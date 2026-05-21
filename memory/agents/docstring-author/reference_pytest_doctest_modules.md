---
name: pytest --doctest-modules is enabled
description: vrcpilot's pyproject sets `--doctest-modules`, so every `>>>` in src docstrings runs during `just test`.
type: reference
---

`pyproject.toml` configures `addopts = ["--strict-markers", "--doctest-modules", ...]`, and `--doctest-modules` traverses both `tests/` and any imported source modules. Every `>>>` in a public-symbol docstring under `src/vrcpilot/` will be executed.

**How to apply:**

- Only include `>>>` examples when output is fully deterministic and does not depend on environment, time, paths, or external services.
- For pure helpers (e.g. `OscConfig.to_launch_arg`), small doctests are valuable as live API demos and cost nothing.
- For anything that performs IO, spawns processes, touches the filesystem, or hits a network — use prose or a fenced code block (no `>>>`).
- Doctest output for strings includes the surrounding repr quotes — write them exactly as the REPL would print, e.g. `'--osc=...'` (single quotes).
- Dataclass `==` comparisons render as `True` / `False`, fine for doctests when the dataclass is `frozen=True` (hashable and comparable).
