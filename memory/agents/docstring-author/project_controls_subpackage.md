---
name: vrcpilot.controls subpackage shape
description: ABC template-method + lazy backend singleton; ensure_target guard is the headline contract
type: project
---

`vrcpilot.controls` (introduced 2026-05-02 on `feature/20260502/controls-linux`)
exposes synthetic mouse / keyboard input. Documentation should consistently
foreground these design decisions because they recur across every public call:

- **Template-method ABC**: `Mouse` / `Keyboard` own the public methods and
  call `ensure_target()` when `focus=True`. Subclasses only implement the
  side-effect `_do_*` half. Document docs on the ABC, not on the backend.
- **`focus=True` default + `focus=False` opt-out**: every public call accepts
  it; mention "set False in hot loops where caller already verified focus"
  consistently.
- **Lazy backend singleton**: `_get()` constructs on first call; `import` is
  side-effect free. uinput device is NOT opened at import.
- **Linux-only this iteration**: Win32 backend not wired. `_get()` raises
  `NotImplementedError` on non-Linux. Explicitly say so in module overviews.
- **Wayland native -> NotImplementedError**: `ensure_target()` fails fast
  rather than warning-and-returning (the rest of `window.*` warns + False).
  Reason: `is_foreground()` always False under native Wayland, retry loop
  would never converge.
- **`Key` is a `StrEnum`**: values follow pydirectinput naming so a future
  Win32 backend can pass `key.value` directly. Linux uses
  `_INPUTTINO_CODES` dict. Test enforces exhaustive mapping.

**Why:** Each of these is a deliberate design tradeoff that callers will hit
within the first 10 minutes of using the API.

**How to apply:** When adding new methods or backends in this subpackage,
mirror the existing docstring template: 1-line purpose, then `focus=` note,
then `Args:` (only for non-obvious params). Don't restate `Literal[...]`
choices in prose. Don't add doctest `>>>` that needs a real uinput device.
