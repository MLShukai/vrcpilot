---
name: user-docs-drift-audit
description: When polishing README / CONTRIBUTING / tests/e2e/README, cross-check Features list, CLI subcommands table, and platform/backend file names against src/ — they drift first
metadata:
  type: project
---

Recurring drift sources to audit before claiming polish is done on `README.md`
/ `README.ja.md` / `CONTRIBUTING.md` / `tests/e2e/README.md`:

1. **Features list vs `src/vrcpilot/__init__.py` `__all__`** — when a new
   public subsystem ships (e.g. OSC, virtual mic), the bullet list lags. Cross-check
   against the import block.
2. **CLI subcommands table vs `_COMMANDS` in `src/vrcpilot/cli/__init__.py`** —
   subcommand additions slip past. The shell-completion `argcomplete` list
   immediately below the table is usually correct (test-pinned) and can act as a
   cheap oracle.
3. **`launch` description ("through Steam")** — direct-spawn became the default
   (Linux always, Windows opt-in); the README description and CLI table sometimes
   still read "Start VRChat through Steam".
4. **Backend file names (`win32.py` / `x11.py` / `proctap.py` / `pipewire.py`)** —
   CLAUDE.md mandates `windows.py` / `linux.py`. CONTRIBUTING.md and
   tests/e2e/README.md sometimes quote the legacy names.
5. **`tests/e2e/README.md` scenario table** — `all.py` auto-discovers any sibling
   `*.py`, so the table goes stale silently the moment a contributor adds a new
   scenario without touching the README. `ls tests/e2e/*.py | grep -v ^_ | grep -v all.py`
   is the source of truth.

**Why:** these four READMEs are bilingual / user-facing surfaces, and the
project ships subsystems faster than the prose tracking them. Each drift
costs new users trust.

**How to apply:** When editing any of these four files, before finishing the
pass, re-run this 5-point checklist against the current `src/` and
`tests/e2e/` state — even if the user's brief did not mention API drift.
Report drifts that are out of scope rather than silently fixing prose around
them.
