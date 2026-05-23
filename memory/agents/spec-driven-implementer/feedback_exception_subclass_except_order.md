---
name: exception-subclass-except-order
description: Subclass exceptions must be caught before their parent or they get silently absorbed
metadata:
  type: feedback
---

When catching multiple related exceptions where one is a subclass of another, the **subclass except block must come first**. Python evaluates `except` clauses top-down and the first match wins; if a parent class appears first, every subclass instance is silently routed into the parent branch.

**Why:** In vrcpilot, `VRChatMultipleInstancesError` is a subclass of `VRChatNotRunningError` (which is a `RuntimeError`). When the CLI wants to print the tailored multi-instance diagnostic ("multiple VRChat instances detected (PIDs: ...); pass --pid") it needs a dedicated `except VRChatMultipleInstancesError` block. Putting `except (VRChatNotRunningError, VRChatNotFocusedError)` first would absorb the multi-instance case and the user would never see the `--pid` hint.

**How to apply:**

- Whenever you add a more-specific exception alongside a broader catch in CLI subcommands (mouse, keyboard, paste, record), put the narrow handler **above** the broad one.
- The same applies to `except RuntimeError` blocks in `record/__init__.py` — `VRChatMultipleInstancesError` (a `RuntimeError`) must be caught before the generic `RuntimeError` branch.
- Run the corresponding `test_multiple_instances_exits_with_diagnostic` test to lock in the order — it explicitly checks the stderr line, which would silently regress otherwise.
