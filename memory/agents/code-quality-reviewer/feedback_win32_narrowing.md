---
name: Win32 platform narrowing pattern
description: Why defensive sys.platform checks inside Windows-only helpers are required (pyright narrowing), not dead code
type: feedback
---

In `src/vrcpilot/`, modules that import Windows-only libraries (`win32gui`, `win32api`, `winreg`, `pywintypes`, etc.) gate the imports under `if sys.platform == "win32":` at module top. Helper functions inside the module that reference those names then need a second `if sys.platform != "win32": raise RuntimeError("unreachable")` near the top of the function body.

**Why:** Without the in-function check, pyright running on POSIX cannot narrow `sys.platform` inside the function scope, so the win32\* names appear unbound and strict mode fails. The runtime branch is genuinely unreachable because the public callers gate on `sys.platform` before calling, but pyright needs the explicit narrowing.

**How to apply:** Do not flag these defensive `unreachable` raises as dead code. Confirm the comment explains the narrowing reason (the `_steam.py` and `window.py` precedents do this well). If a reviewer suggests removing it, push back — pyright strict on `./src/` will break on POSIX CI runs.
