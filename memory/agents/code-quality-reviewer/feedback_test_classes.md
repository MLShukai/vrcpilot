---
name: Test class organization in vrcpilot
description: Tests use `class Test<Target>:` grouping with no return-type annotations, mocker from pytest_mock
type: feedback
---

Tests in `tests/` are organized as `class Test<Target>:` (e.g. `TestFocus`, `TestUnfocus`, `TestPlatformGuard`, `TestLaunch`, `TestFindPid`). Test methods take no return-type annotation. Mocking uses the `mocker: MockerFixture` fixture from `pytest_mock`.

**Why:** Documented in CLAUDE.md plus user's persistent memory. The class grouping mirrors the structure of the SUT and keeps related setup co-located. The `mocker` fixture (rather than `unittest.mock`) is the project standard and gives automatic per-test cleanup.

**How to apply:** When reviewing a new test file:

- Flag flat `def test_*` functions outside a class as a deviation
- Flag `-> None` annotations on test methods as unnecessary
- Flag direct use of `unittest.mock.patch` decorators where `mocker.patch(...)` would do
- For platform-conditional tests, prefer the `@only_windows` / `@only_linux` decorators from `tests/helpers.py` over inline `pytest.mark.skipif`
- For `sys.platform` patching that needs to work on either OS, use `monkeypatch.setattr("<module>.sys.platform", "linux")` — established pattern in `test_steam.py` and `test_window.py::TestPlatformGuard`
