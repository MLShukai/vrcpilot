"""Shared test helpers.

Skip markers, environment probes, and lightweight polling utilities
shared between the automated test suite and the e2e scenarios under
``tests/e2e/``. Anything platform- or display-specific lives here so
that individual test modules can decide at file scope whether to run.
"""

from __future__ import annotations

import functools
import sys
from collections.abc import Sequence
from typing import override

import numpy as np
import pytest
from numpy.typing import NDArray

from vrcpilot import process
from vrcpilot.controls.keyboard import Key, Keyboard
from vrcpilot.controls.mouse import Mouse, MouseButton
from vrcpilot.detect import DetectEngine, Detection
from vrcpilot.speaker.base import CHANNELS, SpeakerBackend

#: Skip a test on non-Windows platforms.
#:
#: Use for tests whose body touches Windows-only APIs (e.g.
#: ``subprocess.CREATE_NEW_PROCESS_GROUP``) that are absent on POSIX runners,
#: even when ``sys.platform`` itself is monkey-patched.
only_windows = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows-only behaviour"
)

#: Skip a test on non-Linux platforms.
#:
#: Use for tests that exercise Linux-specific behaviour and would fail on
#: Windows runners regardless of ``sys.platform`` patching.
only_linux = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux-only behaviour"
)


@functools.lru_cache(maxsize=1)
def has_x11_display() -> bool:
    """Return ``True`` when an X11 display is reachable on this host.

    Probes by opening and immediately closing a connection via
    ``Xlib.display.Display()``. Cached because the underlying state
    cannot change during a pytest run, and probing repeatedly would
    leak X server file descriptors on Linux CI.

    Returns ``False`` on non-Linux platforms unconditionally; ``Xlib``
    is a Linux-only dependency in this project.
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        import Xlib.display

        display = Xlib.display.Display()
    except Exception:
        return False
    try:
        display.close()
    except Exception:
        pass
    return True


#: Skip a test when the Linux X11 display is unavailable.
#:
#: Use this on tests that exercise the real ``Xlib`` paths (window
#: lookup, focus, capture). Tests that purely simulate X11 with the
#: ``tests.fakes.x11`` doubles do not need this marker.
requires_x11_display = pytest.mark.skipif(
    not has_x11_display(), reason="X11 display unavailable"
)

#: Re-exported polling defaults for the e2e ``_helpers`` import surface.
#: Both constants forward to :mod:`vrcpilot.process` so changing one
#: place updates the whole project.
_PID_WAIT_TIMEOUT: float = process.PID_WAIT_TIMEOUT
_PID_WAIT_INTERVAL: float = process.PID_WAIT_INTERVAL


def wait_for_pid(
    timeout: float = _PID_WAIT_TIMEOUT,
    interval: float = _PID_WAIT_INTERVAL,
) -> int | None:
    """Poll for a VRChat PID via :func:`vrcpilot.process.wait_for_pid`.

    Thin wrapper preserved for the e2e ``_helpers`` import surface;
    new call sites should use :func:`vrcpilot.process.wait_for_pid`
    directly.
    """
    return process.wait_for_pid(timeout=timeout, interval=interval)


def wait_for_no_pid(
    timeout: float = _PID_WAIT_TIMEOUT,
    interval: float = _PID_WAIT_INTERVAL,
) -> bool:
    """Poll for VRChat absence via :func:`vrcpilot.process.wait_for_no_pid`.

    Thin wrapper preserved for the e2e ``_helpers`` import surface;
    new call sites should use :func:`vrcpilot.process.wait_for_no_pid`
    directly.
    """
    return process.wait_for_no_pid(timeout=timeout, interval=interval)


class ImplMouse(Mouse):
    """Concrete :class:`Mouse` for ABC template-method tests.

    Records every ``_do_*`` invocation in :attr:`calls` as
    ``(method_name, kwargs_dict)`` tuples. Tests use this in place of
    a mock so the real ABC plumbing (focus guard, kwarg forwarding) is
    exercised end-to-end -- per the project rule that ABC wiring tests
    use a real impl rather than ``mocker.Mock``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    @override
    def _do_move(self, x: int, y: int, *, relative: bool) -> None:
        self.calls.append(("_do_move", {"x": x, "y": y, "relative": relative}))

    @override
    def _do_press(self, button: MouseButton) -> None:
        self.calls.append(("_do_press", {"button": button}))

    @override
    def _do_release(self, button: MouseButton) -> None:
        self.calls.append(("_do_release", {"button": button}))

    @override
    def _do_scroll(self, amount: int) -> None:
        self.calls.append(("_do_scroll", {"amount": amount}))


class ImplKeyboard(Keyboard):
    """Concrete :class:`Keyboard` for ABC template-method tests.

    Records every ``_do_*`` invocation in :attr:`calls` as
    ``(method_name, kwargs_dict)`` tuples. Mirrors :class:`ImplMouse`
    so the keyboard ABC plumbing (focus guard, kwarg forwarding) can
    be exercised end-to-end without the inputtino backend.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    @override
    def _do_down(self, key: Key) -> None:
        self.calls.append(("_do_down", {"key": key}))

    @override
    def _do_up(self, key: Key) -> None:
        self.calls.append(("_do_up", {"key": key}))


class ImplSpeakerBackend(SpeakerBackend):
    """Concrete :class:`SpeakerBackend` for ABC tests.

    Returns whatever ndarray is set on :attr:`buffer` from
    :meth:`read` (defaulting to an empty ``(0, CHANNELS)`` buffer so
    the documented shape contract holds without a real audio source).
    Tests use this in place of a mock so the real ABC plumbing is
    exercised end-to-end -- per the project rule that ABC tests use
    a real impl rather than ``mocker.Mock``.
    """

    def __init__(self, buffer: NDArray[np.float32] | None = None) -> None:
        self.buffer: NDArray[np.float32] = (
            buffer if buffer is not None else np.zeros((0, CHANNELS), dtype=np.float32)
        )

    @override
    def read(self) -> NDArray[np.float32]:
        return self.buffer

    @override
    def close(self) -> None:
        # Intentionally a no-op: the ABC only requires idempotence,
        # which a no-op trivially satisfies.
        return None


class ImplDetectEngine(DetectEngine):
    """Concrete :class:`DetectEngine` for ABC tests.

    Records every ``detect`` invocation in :attr:`calls` as
    ``(image, query)`` ndarray pairs and returns whatever sequence is
    set on :attr:`result`. Tests use this in place of a mock so the
    real ABC plumbing is exercised end-to-end -- per the project rule
    that ABC tests use a real impl rather than ``mocker.Mock``.
    """

    def __init__(self, result: Sequence[Detection] = ()) -> None:
        self.calls: list[tuple[NDArray[np.uint8], NDArray[np.uint8]]] = []
        self.result: Sequence[Detection] = result

    @override
    def detect(
        self,
        image: NDArray[np.uint8],
        query: NDArray[np.uint8],
    ) -> Sequence[Detection]:
        self.calls.append((image, query))
        return self.result
