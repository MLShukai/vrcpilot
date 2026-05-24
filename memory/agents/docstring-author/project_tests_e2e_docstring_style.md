---
name: project-tests-e2e-docstring-style
description: tests/e2e/ scenarios follow a strict module-docstring shape - "E2E scenario: <intent>" + body + "Run with::" code block + artifact path; non-scenario helpers under tests/e2e/ keep an explanatory module doc but do NOT use the "E2E scenario:" prefix
metadata:
  type: project
---

`tests/e2e/` module docstrings follow a stable house style. Maintain
it when adding or polishing scenarios; deviating creates visible
inconsistency in the suite header listing.

**Scenario files (`tests/e2e/<name>.py`, no underscore prefix):**

1. Summary line: `"""E2E scenario: <imperative intent in one sentence>.` (period).
2. Body paragraph: what API surface is verified, against what oracle, plus how the artifacts look.
3. Optional numbered `Steps:` list when the flow is non-trivial (see `ocr.py`).
4. `Run with::` block (RST literal) naming `just e2e-test <name>` -- always present so a reader can copy/paste.
5. `Prerequisites:` bullet list when external setup is required (`clipboard.py`, `keyboard.py`, `mouse.py`, `mic.py`).
6. Artifact path mention pointing under `_e2e_artifacts/`.

**Non-scenario files (`_helpers.py`, `_pyav_recorder.py`, `all.py`):**

Do NOT use the "E2E scenario:" prefix -- these are not scenarios. They
keep a normal `"""<role>` first-line summary plus expanded body. `all.py`
opens with `"""Run every e2e scenario..."` (runner role), `_helpers.py`
with `"""Shared utilities for..."` (helper role).

**Why:**

- 2026-05-24 polish pass found the prefix already in place across all 19
  scenarios; the runner / helpers correctly stayed out of the pattern.
  Future passes should preserve the asymmetry.

**How to apply:**

- New scenarios: copy the header shape from a peer (`focus_unfocus.py`
  is the simplest, `ocr.py` the most structured).
- Polish existing scenarios only when a header element is missing
  (e.g. `Run with::` block), not to enforce uniform paragraph length.
- Never add the "E2E scenario:" prefix to underscore-prefixed helpers
  or the `all.py` aggregator.
