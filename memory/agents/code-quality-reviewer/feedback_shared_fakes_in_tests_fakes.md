---
name: Shared fakes live in tests/fakes/
description: Even single-consumer fakes that mirror a public collaborator class must live in tests/fakes/, not as local _Fake* classes inside individual test files.
type: feedback
---

When a test needs a fake for a public collaborator class (e.g. `Speaker`,
`Capture`, `Mp4FrameSink`), the fake must be defined in `tests/fakes/` and
imported via `from tests.fakes import FakeFoo`. Ad-hoc local `_FakeFoo`
classes inside a single test file are **not** acceptable, even when only
one suite currently consumes the fake.

**Why:** The rule in `CLAUDE.md` ("共有 fake は `tests/fakes/`") and the
docstring of `tests/fakes/__init__.py` ("Tests must NOT define their own
ad-hoc `_Fake*` classes for shared collaborators") apply to *kind of*
collaborator, not *number of current consumers*. The parallel
`FakeCapture` in `tests/fakes/capture.py` is only consumed by
`tests/vrcpilot/capture/test_loop.py`, and that is still where it lives.
"Single consumer" is not a valid carve-out — every shared fake starts
with one consumer.

**How to apply:** When reviewing a new test file that introduces a
`_Fake<PublicClass>` definition, move it into the appropriate
`tests/fakes/<topic>.py` module, add it to `tests/fakes/__init__.py`'s
re-exports and `__all__`, and rename to `FakeFoo` (drop the leading
underscore — the file is private but the class is shared across the
test suite).
