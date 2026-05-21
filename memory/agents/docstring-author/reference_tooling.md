---
name: vrcpilot tooling and verification commands
description: How to run formatters / tests / type checks for vrcpilot and what they enforce on docstrings.
type: reference
---

vrcpilot uses `uv` + `just` as the entry layer. Verification before committing docstring changes:

- `just format` — runs pre-commit (ruff fix + format, **docformatter**, mdformat, codespell, etc.). Docformatter will rewrite docstrings in place; expect it to re-flow your prose. After it runs, re-stage and re-commit if needed.
- `just test` — `uv run pytest -v --cov`, with `--doctest-modules` collecting doctests from imported sources too.
- `just type` — `uv run pyright` in **strict** mode against `./src/`.
- `just run` — chains format → test → type.

**Docformatter quirks observed:**

- Wraps prose at line-length 88 and rewrites the summary line to fit on the first line. Avoid summaries that can be split awkwardly.
- Preserves doctest blocks exactly — safe to include `>>>` lines without docformatter mangling them.

**Pyright strict surface:**

- `./src/` only; `tests/` is excluded.
- `reportImplicitOverride` enabled, `reportPrivateUsage` set to warning.
- Docstrings cannot contradict type hints (e.g. don't say "returns `None`" if the signature returns `str`).

**Commit hooks:**

- `--no-verify` is discouraged. If docformatter/ruff rewrites files on commit, restage and re-commit.
