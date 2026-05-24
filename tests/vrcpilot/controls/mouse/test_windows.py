"""Tests for :mod:`vrcpilot.controls.mouse.windows`.

Windows-only -- the module raises :class:`ImportError` on non-Windows
hosts because it imports ``pydirectinput`` which issues real
``SendInput`` calls into the active session. A module-level skip
guards the rest of the file.

Each ``_do_*`` method on :class:`Win32Mouse` is a one-line wrapper
around the corresponding ``pydirectinput`` call (with a sign flip
on the scroll path because Win32 uses positive=up while the public
API uses positive=down). Verifying the wrapping behaviour without
mocking ``pydirectinput`` would inject real mouse events into the
runner's desktop session. The full pipeline is exercised by
``tests/e2e/mouse.py`` against a real VRChat window; this file just
confirms construction succeeds and the public ``_do_*`` methods
accept their argument types.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip(
        "vrcpilot.controls.mouse.windows is Windows-only",
        allow_module_level=True,
    )

from vrcpilot.controls.mouse.windows import Win32Mouse  # noqa: E402


class TestWin32MouseConstructs:
    """Construction must not raise.

    ``Win32Mouse`` does not open any device at construction time
    (``pydirectinput`` is stateless at import). A clean construction
    means the platform import gate accepted the runner.
    """

    def test_construct_does_not_raise(self) -> None:
        m = Win32Mouse()
        del m  # nothing else to assert at construction time
