---
name: This agent has no shell tool — cannot run just / git directly
description: The docstring-author agent is invoked without Bash/PowerShell access; verification and commits must be handed back to the user.
type: feedback
---

When invoked as the `docstring-author` agent in this project, no Bash or PowerShell tool is exposed (only Read/Edit/Glob/Grep/Write + a few deferred non-shell tools).

**Why:** Observed in the 2026-04-27 launch-options docstring task — the user asked for `just run` and a commit, but no execution tool was available. Trying to fabricate a verification result, or running pre-commit through any indirect channel, would mislead the user.

**How to apply:**

- After making docstring edits, do not promise that `just run` was executed. Explicitly hand the verification + commit step back to the user with the exact commands they should run.
- Mention any doctests added so the user knows what would change in test runs.
- Skip "running" steps in todos; structure work as edit → self-check → handoff report.
