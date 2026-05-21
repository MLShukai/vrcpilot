---
name: vrcpilot CLI subcommand docstring conventions
description: Docstring shape shared by src/vrcpilot/cli/*.py modules — module-level patch-target note, register/run signatures, exit-code prose
type: project
---

`src/vrcpilot/cli/*.py` modules follow a consistent docstring shape. When
documenting a new or revised CLI subcommand, mirror this:

- **Module docstring** opens with `"vrcpilot <name>" subcommand.` then a
  one-paragraph statement of (a) what underlying module it wraps, (b) which
  actions are exposed, and (c) why any actions are intentionally omitted
  (e.g. `mouse press` / `keyboard down` cannot survive
  `/dev/uinput` device close across CLI invocations).
- The module docstring ends by naming the **stable patch target** used by
  tests: `mouse_api` / `keyboard_api` aliases for `mouse` /
  `keyboard`; `_make_sender` factory for `osc`. Tests bind fakes by
  patching this single symbol — call it out explicitly so future maintainers
  preserve the seam.
- **`register(subparsers)`** docstring: one line stating it adds the
  subparser (and sub-subparsers if any). Keep it short; argparse `help=`
  strings carry per-flag detail.
- **`run(args)`** docstring: states that success is silent, lists exit
  codes (0/1/2) inline as prose. The `Returns:` block is acceptable but
  becomes redundant if prose already enumerates the codes — prefer
  prose-only when the cases are simple.
- **Exit code prose** convention: `1` for guard / validation failures
  surfaced as `vrcpilot: <message>` on stderr; `2` for "input required
  but stdin is a tty" (mirrors `paste` / `chatbox`); argparse handles
  malformed usage upstream and exits non-zero on its own.

**Why:** The cli/\* modules are the documented entry points users invoke
via `uv run vrcpilot ...`. Consistency across them lets users predict
exit semantics without re-reading each file.

**How to apply:** When a new cli/<name>.py lands, the module docstring
should look at `cli/mouse.py` first for the patch-target paragraph
shape, then at `cli/paste.py` for stdin/tty exit-2 prose. Keep
`register()` to a single line; `run()` to one short paragraph.
