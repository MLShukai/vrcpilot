---
name: argcomplete reference facts
description: Verified facts about argcomplete as of 2026-04-27 (v3.6.3) — PowerShell support, FilesCompleter, marker placement
type: reference
---

Verified via PyPI + upstream source on 2026-04-27.

- Latest stable: **3.6.3**, `requires-python = ">=3.8"`, classifiers cover 3.8–3.13 (no 3.14 classifier yet, but no upper pin).
- `register-python-argcomplete` accepts `--shell` with `choices=("bash", "zsh", "tcsh", "fish", "powershell")`. `pwsh` is NOT accepted; full `powershell` only.
- Official docs say maintainers support only bash/zsh, and PowerShell support lives in `contrib/`. The `--shell powershell` option does exist in `scripts/register_python_argcomplete.py` choices, so it works, but it's "contrib-quality".
- PowerShell activation pattern documented in contrib README: `register-python-argcomplete --shell powershell <prog> | Out-String | Invoke-Expression`.
- `FilesCompleter(allowednames=(), directories=True)` — `allowednames` is normalized via `x.lstrip("*").lstrip(".")`, so `"exe"` and `".exe"` and `"*.exe"` are equivalent.
- `PYTHON_ARGCOMPLETE_OK` marker must appear in the **first 1024 bytes** of the file containing the entry point. Can follow a shebang (and by extension a docstring or `from __future__`), but earlier is safer.
