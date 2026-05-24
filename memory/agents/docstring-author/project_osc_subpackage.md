---
name: vrcpilot.osc docstring conventions
description: Recurring docstring intents for the OSC send-side package (sender / controller / avatar)
metadata:
  type: project
---

`vrcpilot.osc` is a thin send-side wrapper over `python-osc` `SimpleUDPClient`,
shaped as `OscSender` (raw send + validation) plus two views constructed by
factory methods: `InputController` (the `/input/*` + `/chatbox/*` surface)
and `AvatarParameters` (the `/avatar/parameters/*` surface). Tests are
*integration-real* over a loopback UDP server (`tests/vrcpilot/osc/conftest.py`).

**Wire-spec details that must survive docstring rewrites:**

- `OscSender.send_bool` writes the OSC `i` tag (0/1), **not** the OSC `T`/`F`
  bool tags — VRChat rejects the latter. Preserve this in the `send_bool`
  docstring on `OscSender`. The `AvatarParameters.send_bool` wrapper inherits
  the same behaviour and should mention "goes through `OscSender.send_bool`"
  so callers know what tag VRChat will see.
- `OscSender.send_float` casts to `float()` even though `int` is a subtype of
  `float` per PEP 484 — without the cast, `send_float("/x", 1)` would emit the
  OSC `i` tag. The intent lives in a `# ...` inline comment; do not move it
  to a docstring (that would document the implementation rather than caller
  contract).
- `INT_RANGE = (0, 255)` and `FLOAT_RANGE = (-1.0, 1.0)` are module-level
  attribute-docs (`#:` syntax). Keep them — they are the only spec for the
  validation ranges. The `send_int` / `send_float` method docstrings should
  reference `:data:` cross-link the constant, not restate the literal range.

**Test-injection seams (`client=` kw-only):**

- `OscSender.__init__(client=...)` bypasses real UDP construction. This is
  *the* test seam for the package and must be documented as such on the class
  docstring. When `client=` is supplied, `host` / `port` are only retained for
  the eponymous properties — they no longer influence delivery. The `host`
  and `port` property docstrings already include "(informational; `client=`
  overrides)" — preserve that wording.

**Method-naming idioms that drive docstring brevity:**

- `InputController` has three flavours of method shaped after the OSC surface:
  axes (float in \[-1.0, 1.0\]), tap (single-shot on→sleep→off), hold
  (explicit `active=True/False`). The class docstring lists all three;
  individual methods get a 1-liner naming the OSC address. Do not re-explain
  the flavour mechanics in each method docstring.
- `voice()` (tap, toggle mode) and `hold_voice(active)` (push-to-mute) target
  the same `/input/Voice` address — document the relationship with a
  `cf. :meth:`voice\`\` cross-link in `hold_voice`.

**Chatbox specifics:**

- `CHATBOX_MAX_LENGTH = 144` mirrors VRChat's documented limit and is the
  validation threshold in `InputController.chatbox`. Constant lives at
  module scope with `#:` doc.
- `chatbox(text, *, send=True, sfx=True)` — `send=False` only fills the input
  field (does not submit); `sfx` toggles the notification chime. Both
  semantic details belong in the method docstring; the type hints already
  document the keyword-only-ness.
