---
name: CLI run() docstrings — exit-code block vs inline prose
description: When `run(args)` has more than one non-zero exit code, prefer a bulleted "Exit codes:" block over inline prose; one-exit-code subcommands stay one-liners.
metadata:
  type: project
---

`src/vrcpilot/cli/*.py` `run(args)` docstrings split cleanly into
three shapes:

- **Single exit + silent success** (`focus`, `unfocus`, `paste`,
  `mouse`, `keyboard`, `pid`, `screenshot`, `terminate`): one-line
  intent + "exit 1 with `vrcpilot: ...` on stderr when X".
- **Two or more non-zero codes** (`launch`, `record`, `osc`, `mic`,
  `paste`): use a `Exit codes:` bulleted list. Each entry says
  *what* exit code + *what condition* triggers it. This is the only
  place per-exit-code rationale lives — do NOT also enumerate codes
  in the summary line.
- **Dispatcher** (`linux_mic.run`): one line + the platform precondition.

**Why:** The CLI subcommand style memory
\[\[project_cli_subcommand_style\]\] tolerates either prose or bullets;
in practice the bulleted form is easier to scan when codes are
multi-axis (e.g. `launch` distinguishes "pre-flight failed" vs
"already running" vs "wait timed out") and the prose form collapses
to noise. Codified during the 2026-05-24 cli/ polish pass.

**How to apply:** When documenting a new CLI subcommand, count the
distinct non-zero exit cases the user can hit. One -> single line.
Two or more -> bulleted `Exit codes:` block under the summary.
Never let the summary line restate the codes a Returns / Exit block
also lists; that's the same drift the
\[\[feedback_docstring_returns\]\] memory warns against, applied to exit
codes.
