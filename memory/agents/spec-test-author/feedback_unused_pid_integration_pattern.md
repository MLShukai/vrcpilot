---
name: unused-pid-integration-pattern
description: Use an unused-but-syntactically-valid PID to drive resolve_pid-then-backend dispatch end-to-end without mocking internal functions
metadata:
  type: feedback
---

When a dispatch helper consults `resolve_pid(pid)` then calls a
platform backend, you can exercise the full code path end-to-end by
passing `pid=99_999_999` (or any other PID guaranteed unused on the
test host):

- `resolve_pid(non_None)` short-circuits on `pid is not None` and
  returns the value unchanged -- so the test does **not** consult
  `find_pids` (no autouse-fixture-dependent state).
- The dispatch forwards the value to the live platform backend
  (`find_vrchat_hwnd` on Windows, `find_vrchat_window` on Linux).
- The real backend walks `EnumWindows` / `_NET_CLIENT_LIST`,
  finds no window owned by the unused PID, and returns `None` /
  `False`.
- The dispatch reflects that as the documented `False` / `None`
  return.

**Why:** This replaces what would otherwise require either
`mocker.patch("vrcpilot.process.resolve_pid", ...)` (banned --
internal function mocking) or `mocker.patch( "vrcpilot.window.windows.find_vrchat_hwnd", ...)` (also banned). The
unused-PID pattern keeps every dispatch + backend boundary real while
producing a deterministic `None` / `False` observable.

**How to apply:** When testing a public dispatch entry point that
takes `pid: int | None = None` and forwards to a platform backend,
prefer passing `pid=99_999_999` for the "VRChat not running"
observable rather than mocking `find_pids` / `resolve_pid`.

**Caveat:** `-1` is **not** equivalent. Some `_NET_WM_PID`
property readers and Win32 EnumWindows-walks reject negative values
earlier than the dispatch path you mean to exercise.

**Related:** \[\[fakes-mirror-production\]\] -- 3rd-party surface fakes
banned. \[\[boundary-assertions\]\] -- assert on the observable return,
not on which Win32 / Xlib calls happened underneath.
