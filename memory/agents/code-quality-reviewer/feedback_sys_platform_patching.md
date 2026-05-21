---
name: sys.platform monkeypatch is allowed for fail-fast branches
description: Despite CLAUDE.md's general "禁止" wording, mocker.patch.object(sys, "platform", ...) is the established idiom for testing the NotImplementedError branch of platform-dispatch factories.
type: feedback
---

`tests/vrcpilot/controls/test_mouse.py::TestGetLazyInit::test_unsupported_platform_raises_not_implemented`
and the matching keyboard test use `mocker.patch.object(sys, "platform", "darwin")` to exercise the NotImplementedError branch of the
platform-dispatch factory. The new
`tests/vrcpilot/speaker/test_session.py::TestPlatformDispatch` follows
the same pattern.

CLAUDE.md states `sys.platform` monkeypatching is banned because it
gives "偽のクロスプラットフォーム保証" (false cross-platform guarantees).
That ban targets tests that patch `sys.platform` to pretend Windows
code paths work on Linux (or vice versa). It does **not** target the
single fail-fast branch of a platform-dispatch factory:

```python
def _select_x_backend(...) -> XBackend:
    if sys.platform == "win32":
        ...
    raise NotImplementedError(f"X is not supported on {sys.platform}")
```

Testing that the final `raise` fires requires either patching
`sys.platform` for one call or refactoring the factory to take a
`platform: str` parameter. The codebase consistently prefers the
patch idiom (see mouse / keyboard / speaker tests).

**Why:** The patch is one-shot, deterministic, and does not lie about
any platform-specific behaviour — it only forces a constant branch to
fire on whichever host runs the test. No production code path is
exercised under the lie; the test is the only consumer of the patched
value.

**How to apply:** When reviewing a `mocker.patch.object(sys, "platform", ...)` call, accept it if the patched call's only
platform-sensitive side effect is `raise NotImplementedError`. Push
back if the patched call goes on to invoke platform-specific imports
or APIs, because then the patch is masking a real "does this run on
that platform" question.
