---
name: project-tests-fakes-docstring-style
description: tests/fakes/<name>.py module docstrings name the production ABC they stand in for, why the fake exists (which tier of tests use it), and explicitly note that 3rd-party library surfaces are NOT faked here
metadata:
  type: project
---

`tests/fakes/` only re-exports stand-ins for **vrcpilot-owned ABCs**.
The module docstring should answer three questions a reader hits when
they open the file:

1. **Which production ABC is mirrored?** Reference the canonical class
   (e.g. `` :class:`vrcpilot.detect.DetectEngine`  ``).
2. **Why use a fake here rather than the real thing?** Usually "the
   real backend is irrelevant to what this test exercises" or "the
   real backend needs hardware/infra that the unit tier should not
   require". Cite the tier (integration-with-fakes vs CLI integration).
3. **Which tests are the customer?** Phase 2C / Phase 3 / CLI tests are
   the common answers; naming them anchors the file in the strategy.

If the docstring would also benefit from listing what attributes the
fake exposes for assertions (`calls`, `last_image`, `instances`), keep
that as one short prose sentence rather than introducing an
`Attributes:` block -- the tests/ tier prefers tight prose.

**Explicit non-goal:** every fakes module docstring should remind the
reader that 3rd-party library surfaces (`pulsectl`, `soundcard`,
`windows_capture`, `proctap`, `pw-record` via `subprocess.Popen`,
`Xlib`, `psutil`, `pyperclip` etc.) are **not** faked here -- see
`tests/fakes/audio.py` and `tests/fakes/capture.py` for the pattern.
Tests that need real 3rd-party behaviour belong in the
integration-real tier.

**How to apply:**

- New fake added to `tests/fakes/`: copy the ABC-name / why / who-uses-it
  triad from `tests/fakes/ocr.py` (a clean compact example) or
  `tests/fakes/audio.py` (the most structured).
- Class docstrings: lead with intent ("OCR engine that always returns a
  fixed word list"), then a sentence on which attributes tests assert
  against. Avoid `Args:` blocks unless an arg carries a non-obvious
  contract.
- Never add a doctest -- `pytest --doctest-modules` is enabled and the
  fakes hold ndarray state that does not serialise well as a `>>>` line.
