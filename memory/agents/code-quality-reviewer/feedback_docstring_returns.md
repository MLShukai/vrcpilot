---
name: Don't restate Returns in the docstring summary paragraph
description: Google-style docstrings should keep return-value contract in the Returns block only
type: feedback
---

In `src/vrcpilot/` Google-style docstrings, the leading paragraph describes *what the function does* and notable behavior; the `Returns:` block describes the return-value contract (success/failure conditions, edge cases). Do not duplicate the success/failure description in both places.

**Why:** Duplication invites drift — one place gets updated, the other goes stale. The user explicitly flagged this in the `focus()` docstring during review.

**How to apply:** When reviewing a docstring, scan the summary paragraph for sentences starting with "Returns `True` ..." or similar. If the same contract appears in the `Returns:` block, strip it from the summary and keep the behavior description ("Restores the window if minimized", "Has no effect in VR exclusive mode", etc.) intact. The summary should answer "what does this do?", not "what does it return?".
