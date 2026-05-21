---
name: User role and collaboration style
description: User is a Japanese-speaking developer building vrcpilot; communicates in Japanese but expects English code/docstrings.
type: user
---

The user develops vrcpilot and addresses Claude in Japanese. They expect:

- Replies in Japanese.
- Code, identifiers, and docstrings in English (consistent with the repo's existing English docs and CLAUDE.md guidance).
- Concise, terse interaction — they read diffs themselves and dislike redundant summaries.
- Comfortable with high autonomy: they delegate implementation/verification cycles to Claude (`just run` etc.) and expect a brief report on completion (changed files, verification result, commit hash, key intent).

**How to apply:**

- Default docstring language: English.
- Default reply language: Japanese.
- Keep final report sections short. Lead with what they would act on (verification result, commit), not what was edited.
