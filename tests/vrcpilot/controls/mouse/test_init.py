"""Tests for :mod:`vrcpilot.controls.mouse` (module-level dispatch).

Mirrors ``keyboard/test_init.py``: the package ``__init__`` exposes
the module-level helpers ``move`` / ``click`` / ``press`` / ``release``
/ ``scroll`` that lazy-construct the platform backend on first call
and cache it in ``_instance``. Tests verify:

* ``_get()`` returns the cached instance after the first call.
* Module-level helpers forward to the backend's public methods.

A :class:`Mouse` subclass (not a mock) is injected into ``_instance``
so dispatch runs end-to-end without opening ``/dev/uinput`` or
touching pydirectinput. The autouse fixture clears the singleton
between tests.

The unsupported-platform branch in ``_get()`` (raises
:class:`NotImplementedError` on neither-Windows-nor-Linux hosts) is
**not** tested here: the only way to reach it from a supported runner
is by patching :attr:`sys.platform`, which the test policy bans.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import override

import pytest

from vrcpilot.controls import mouse as mouse_mod
from vrcpilot.controls.mouse.base import Mouse, MouseButton


@pytest.fixture(autouse=True)
def _reset_mouse_singleton() -> Iterator[None]:
    """Clear the module-level lazy backend before and after each test."""
    mouse_mod._instance = None
    yield
    mouse_mod._instance = None


class _RecordingMouse(Mouse):
    """Concrete :class:`Mouse` that records ``(method, kwargs)`` calls.

    Distinct from :class:`tests.helpers.ImplMouse`: that fixture
    records ``_do_*`` (the ABC's leaves), whereas the module-level
    dispatch tests need to assert which **public** method was invoked
    on the backend. Overrides the public methods directly.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    @override
    def move(
        self,
        x: int,
        y: int,
        *,
        relative: bool = False,
        focus: bool = True,
        pid: int | None = None,
    ) -> None:
        self.calls.append(
            (
                "move",
                {
                    "x": x,
                    "y": y,
                    "relative": relative,
                    "focus": focus,
                    "pid": pid,
                },
            )
        )

    @override
    def click(
        self,
        *buttons: MouseButton,
        count: int = 1,
        duration: float = 0.0,
        interval: float = 0.0,
        focus: bool = True,
        pid: int | None = None,
    ) -> None:
        self.calls.append(
            (
                "click",
                {
                    "buttons": buttons,
                    "count": count,
                    "duration": duration,
                    "interval": interval,
                    "focus": focus,
                    "pid": pid,
                },
            )
        )

    @override
    def press(
        self,
        *buttons: MouseButton,
        focus: bool = True,
        pid: int | None = None,
    ) -> None:
        self.calls.append(("press", {"buttons": buttons, "focus": focus, "pid": pid}))

    @override
    def release(
        self,
        *buttons: MouseButton,
        focus: bool = True,
        pid: int | None = None,
    ) -> None:
        self.calls.append(("release", {"buttons": buttons, "focus": focus, "pid": pid}))

    @override
    def scroll(
        self, amount: int, *, focus: bool = True, pid: int | None = None
    ) -> None:
        self.calls.append(("scroll", {"amount": amount, "focus": focus, "pid": pid}))

    @override
    def _do_move(
        self, x: int, y: int, *, relative: bool
    ) -> None:  # pragma: no cover - unused
        raise AssertionError("public methods are overridden; _do_* must not run")

    @override
    def _do_press(self, button: MouseButton) -> None:  # pragma: no cover - unused
        raise AssertionError("public methods are overridden; _do_* must not run")

    @override
    def _do_release(self, button: MouseButton) -> None:  # pragma: no cover - unused
        raise AssertionError("public methods are overridden; _do_* must not run")

    @override
    def _do_scroll(self, amount: int) -> None:  # pragma: no cover - unused
        raise AssertionError("public methods are overridden; _do_* must not run")


class TestLazySingleton:
    """``_get()`` caches the backend after first construction."""

    def test_returns_cached_instance_after_first_call(self) -> None:
        backend = _RecordingMouse()
        mouse_mod._instance = backend

        assert mouse_mod._get() is backend
        assert mouse_mod._get() is backend


class TestModuleFunctionForwarding:
    """Module-level helpers forward ``*args`` and ``**kwargs`` unchanged."""

    def test_move_forwards(self) -> None:
        backend = _RecordingMouse()
        mouse_mod._instance = backend

        mouse_mod.move(100, 200, relative=True, focus=False, pid=9999)

        assert backend.calls == [
            (
                "move",
                {
                    "x": 100,
                    "y": 200,
                    "relative": True,
                    "focus": False,
                    "pid": 9999,
                },
            )
        ]

    def test_click_forwards_with_defaults(self) -> None:
        backend = _RecordingMouse()
        mouse_mod._instance = backend

        mouse_mod.click(MouseButton.RIGHT)

        assert backend.calls == [
            (
                "click",
                {
                    "buttons": (MouseButton.RIGHT,),
                    "count": 1,
                    "duration": 0.0,
                    "interval": 0.0,
                    "focus": True,
                    "pid": None,
                },
            )
        ]

    def test_click_forwards_combo_and_overrides(self) -> None:
        backend = _RecordingMouse()
        mouse_mod._instance = backend

        mouse_mod.click(
            MouseButton.LEFT,
            MouseButton.RIGHT,
            count=2,
            duration=0.05,
            interval=0.07,
            focus=False,
            pid=9999,
        )

        assert backend.calls == [
            (
                "click",
                {
                    "buttons": (MouseButton.LEFT, MouseButton.RIGHT),
                    "count": 2,
                    "duration": 0.05,
                    "interval": 0.07,
                    "focus": False,
                    "pid": 9999,
                },
            )
        ]

    def test_press_and_release_forward(self) -> None:
        backend = _RecordingMouse()
        mouse_mod._instance = backend

        mouse_mod.press(MouseButton.MIDDLE)
        mouse_mod.release(MouseButton.MIDDLE, focus=False, pid=9999)

        assert backend.calls == [
            (
                "press",
                {"buttons": (MouseButton.MIDDLE,), "focus": True, "pid": None},
            ),
            (
                "release",
                {"buttons": (MouseButton.MIDDLE,), "focus": False, "pid": 9999},
            ),
        ]

    def test_scroll_forwards(self) -> None:
        backend = _RecordingMouse()
        mouse_mod._instance = backend

        mouse_mod.scroll(-2, focus=False, pid=9999)

        assert backend.calls == [
            ("scroll", {"amount": -2, "focus": False, "pid": 9999}),
        ]
