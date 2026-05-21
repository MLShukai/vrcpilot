---
name: Avoid object-typed fixture parameters in tests
description: Don't annotate fixture-injected mock parameters as `: object`; leave unannotated to avoid pyright-ignore noise
type: feedback
---

When a test method receives a fixture that returns a `MagicMock`/`Mock` (e.g. from `mocker.patch.object`), do NOT annotate the parameter as `: object`. That annotation forces every mock attribute access (`return_value`, `call_count`, `call_args_list`, `mock_calls`) to need a `# pyright: ignore[reportAttributeAccessIssue]` comment, which is noise.

**Why:** `tests/` is excluded from pyright strict (`pyright.exclude = ["tests/"]` in pyproject.toml), so unannotated parameters are fine. Annotating as `: object` is the worst of both worlds — it neither documents the type accurately (it's a `MagicMock`, not an opaque object) nor lets pyright help, and it adds ignore comments that the project otherwise keeps minimal.

**How to apply:**

- In tests that take a fixture-provided mock, leave the parameter unannotated: `def test_x(self, mocker: MockerFixture, mock_thing):`
- If a type annotation is genuinely useful (e.g. for IDE help), prefer `pytest_mock.MockType` (or `unittest.mock.MagicMock`) over `object`
- Flag `: object` annotations on mock fixture parameters and the resulting `# pyright: ignore` chain as cleanup
