---
name: parallel-fixer-isolation
description: When fixers run in parallel sharing a working tree, reset out-of-scope files before each commit to avoid pre-commit cycles failing
metadata:
  type: feedback
---

When multiple fixer agents (F1 / F2 / F3 etc.) run in parallel against the
same git working tree, each fixer's pre-commit run can briefly write the
other fixers' in-flight edits into your working tree. Symptom: `git status`
shows files you never touched (e.g. `src/vrcpilot/__init__.py` when you only
edited `CHANGELOG.md`), and `pre-commit` rejects your commit with "Unstaged
files detected".

**Why:** Concurrent edits leak through the shared filesystem and pre-commit's
stash/restore cycle picks them up.

**How to apply:** Before each commit:

1. Confirm scope: re-read the instruction's "触ってはいけないファイル" list.
2. `git checkout -- <out-of-scope-file>` for any file outside your scope.
3. `git status` to confirm only your files are modified.
4. `git add <your-files>` and `git commit -m ...`.
5. If `just test` fails because a concurrent fixer landed only half of a
   coupled change (e.g. F1 committed `__init__.py` narrowing but not
   `test_init.py` updates), reset the offending file in your working tree
   and re-run tests. Do NOT try to "help" by fixing the other fixer's
   missing pieces — that's their scope and your commit would conflict.

Also: when CHANGELOG-style edits need to anticipate a concurrent fixer's
work, write them based on **known plan content** (provided in the
instruction), not by reading the live working tree mid-flight.
