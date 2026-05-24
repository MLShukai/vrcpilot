---
name: tkinter-stub-window-pattern
description: Use stdlib tkinter to spawn a real top-level window for X11 / Win32 backend integration-real tests; matches by os.getpid() rather than process name
metadata:
  type: feedback
---

For `vrcpilot.window.*` and `vrcpilot.{linux,windows}` backend
tests, spawn a real `tkinter.Tk()` top-level window in a fixture and
drive the production helpers against it. The fixture pattern:

```python
@pytest.fixture
def tk_window() -> Iterator[tkinter.Tk]:
    root = tkinter.Tk()
    root.geometry("320x240+50+60")
    root.update_idletasks()
    root.update()  # forces WM round-trip; window is now mapped
    try:
        yield root
    finally:
        root.destroy()
```

The production matchers (`find_vrchat_hwnd` on Windows,
`find_vrchat_window` on Linux) match on **PID**, not process name,
so a window owned by the test's `os.getpid()` is discoverable by
the helpers exactly the same way VRChat is at runtime. This lets the
EWMH / Win32 round-trip be exercised with zero faking.

**Why:**

- tkinter is in the stdlib -- no extra dev dep.
- The window is real, the WM round-trip is real, the property reads
  are real. Pure integration-real per the testing skill.
- Replaces `FakeXDisplay` / `FakeXWindow` (3rd-party-surface
  fakes, banned for new code) and `mocker.patch` of
  `find_vrchat_hwnd` / `find_vrchat_window` (internal-function
  mocking, banned).

**How to apply:**

- On Linux: gate the file with module-level skips on
  `sys.platform != "linux"` and `not has_x11_display()` so
  DISPLAY-less hosts skip cleanly. Xvfb is fine; native Wayland is
  not (the production helpers themselves short-circuit on native
  Wayland).
- On Windows: gate the file with module-level skip on
  `sys.platform != "win32"`. The GitHub Actions Windows runner has
  a session that supports tkinter.
- The `is_foreground` happy path is only reliably True for windows
  owned by the current process when `SetForegroundWindow` /
  `_NET_ACTIVE_WINDOW` succeeds. On a shared X session it may be
  flaky -- only assert `True` after a successful `focus_window`
  call on the same window.
- The "window destroyed mid-call" race (XError / pywintypes.error
  branch) can be driven by destroying the tk window between
  `find` and the rect query. On X11 you need `display.sync()`
  between destroy and the rect read for the deletion to be observed.

**Related:** \[\[unused-pid-integration-pattern\]\] -- complementary
pattern for the "no window owns this PID" branch.
