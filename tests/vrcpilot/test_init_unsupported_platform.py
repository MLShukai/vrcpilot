"""Unsupported-platform gate at the top of ``vrcpilot.__init__``.

The gate at the very top of :mod:`vrcpilot.__init__` is the package's
first line of defence on hosts other than ``win32`` / ``linux``: any
unsupported ``sys.platform`` must raise ``ImportError`` *before* the
subpackages (which import platform-specific 3rd-party deps) get a
chance to load and fail with a misleading missing-dependency error.

This file deliberately uses an **inverted module-level skip**: it
runs only on hosts where ``sys.platform`` is genuinely something
other than ``win32`` / ``linux`` (macOS, FreeBSD, etc.). The project
does not target those hosts and CI does not exercise them, so the
file will skip in practice — and that is the point. Monkey-patching
``sys.platform`` to fake an unsupported host would test our patching
machinery rather than the gate itself; we keep the gate's contract
honest by relying on a real unsupported runtime when one exists.

Net effect: if a future CI matrix adds e.g. macOS, this file starts
collecting and the gate's behaviour is checked against a real host
instead of a synthetic one.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform in ("win32", "linux"):
    pytest.skip(
        "Inverted gate: this file only runs on unsupported hosts.",
        allow_module_level=True,
    )


pytestmark = pytest.mark.api_contract


class TestUnsupportedPlatformGate:
    def test_import_raises_with_clear_diagnostic(self) -> None:
        # The gate's message has to name the package and the offending
        # platform so users get a clear "we don't support this OS"
        # signal rather than a generic ImportError from a deeper
        # backend dep.
        with pytest.raises(ImportError, match="vrcpilot supports only"):
            import vrcpilot  # noqa: F401
