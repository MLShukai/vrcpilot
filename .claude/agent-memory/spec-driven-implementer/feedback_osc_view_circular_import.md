---
name: OSC view modules - importing SupportsBool eagerly causes a real circular import
description: In src/vrcpilot/osc, sender.py imports avatar/controller eagerly, so view modules cannot do `from .sender import SupportsBool` at module top - use TYPE_CHECKING.
type: feedback
---

`src/vrcpilot/osc/avatar.py` (and `controller.py` by analogy) sit on the
opposite side of a real import cycle with `sender.py`:

```
osc/__init__.py → sender.py → (eager) `from . import avatar, controller`
                                         → avatar.py → `from .sender import SupportsBool`  # boom
```

`sender.py` runs the `from . import avatar` line *before* the
`SupportsBool` symbol is defined in its own module body, so when
`avatar.py` tries to bind `SupportsBool` from a partially-initialised
`sender` module, it fails with `ImportError: cannot import name 'SupportsBool' from partially initialized module`.

**Why:** the planning doc in
`/home/gop/.claude/plans/claude-vrchat-osc-...` explicitly suggested
`from .sender import SupportsBool` would work alongside
`from __future__ import annotations`. It does not — `from __future__ import annotations` only defers *annotations*, not the actual runtime
import statement.

**How to apply:** when writing `osc/avatar.py` / `osc/controller.py`
(and any future view that needs `SupportsBool`), put the import under
`TYPE_CHECKING`:

```python
from __future__ import annotations
from typing import TYPE_CHECKING
from . import sender
if TYPE_CHECKING:
    from .sender import SupportsBool
```

Then reference `SupportsBool` only in annotations (which `from __future__ import annotations` keeps as strings). Don't try to use it
at runtime in these modules — if you need an `isinstance(x, SupportsBool)` check, do it inside `OscSender` itself.
