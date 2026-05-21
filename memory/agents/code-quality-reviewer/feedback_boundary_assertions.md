---
name: Boundary-call assertions are not "internal implementation testing"
description: When asserting mock call arguments crosses the line from contract to implementation testing
type: feedback
---

CLAUDE.md says "do not test internal implementation details." This rule does NOT forbid asserting the arguments passed to mocked OS / external boundary calls.

**Why:** The distinction is about *what* the assertion verifies. Asserting `SetForegroundWindow.assert_called_once_with(hwnd)` checks the public contract with the OS — that the right window handle reaches the boundary. Asserting that an internal helper was called, or asserting on intermediate state, would be implementation testing. The former survives refactors; the latter doesn't.

**How to apply:** When reviewing a mocker assertion, ask: "would this break for a legitimate refactor that preserves behavior?" If the mocked target is an external/OS API and the assertion checks the load-bearing argument (the HWND, the path, the URL), it's a boundary contract test — accept it. If it checks call counts on multiple internal mocks just to verify the order of operations, push back.

Example accepted in `tests/test_window.py::TestFocus::test_returns_true_on_success`: only `SetForegroundWindow(12345)` is asserted; `BringWindowToTop` and `keybd_event` are mocked but not asserted, which is correct minimum-surface behavior testing.
