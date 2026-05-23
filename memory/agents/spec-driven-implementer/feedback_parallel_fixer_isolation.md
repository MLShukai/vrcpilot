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

**Edit-tool silent revert under concurrent stash/restore:** A concurrent
fixer's `pre-commit` (which does `git stash` -> hook run -> `git stash pop`)
can revert your Edit-tool changes between your Edit call and the next
inspection — the tool reports success but the file content shown in the
next system-reminder is the pre-Edit state, and `git diff` shows nothing.
When you suspect this:

1. Run `git diff <file>` immediately after Edit; an empty diff confirms the
   revert happened.
2. Fall back to the Write tool with the full intended file content. Write
   appears to win the race more reliably than Edit (single-shot full
   overwrite vs read-modify-write).
3. Run `git diff` again to confirm the Write took effect, then commit
   immediately — every minute of delay invites another revert.
