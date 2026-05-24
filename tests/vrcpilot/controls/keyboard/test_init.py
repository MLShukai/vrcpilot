"""Tests for :mod:`vrcpilot.controls.keyboard` (module-level dispatch).

The package ``__init__`` exposes the module-level helpers ``press`` /
``down`` / ``up`` that lazy-construct the platform backend on first
call and cache it in ``_instance``. Tests here verify:

* The lazy singleton behaviour -- ``_get()`` returns the cached
  instance after the first construction.
* The module-level helpers forward correctly to the backend's public
  ``press`` / ``down`` / ``up`` methods (no reshape, no extra kwargs).

A subclass of :class:`Keyboard` (not a mock) is injected into
``_instance`` so dispatch runs end-to-end without opening
``/dev/uinput`` or touching pydirectinput. The autouse fixture below
clears the singleton between tests so backend construction order does
not leak between cases.

The unsupported-platform branch in ``_get()`` (raises
:class:`NotImplementedError` on neither-Windows-nor-Linux hosts) is
**not** tested here: the only way to reach it from a supported runner
is by patching :attr:`sys.platform`, which the test policy bans
because it gives false cross-platform guarantees. The branch is a
one-line defensive raise that surfaces naturally if a user ever
imports on an unsupported host.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import override

import pytest

from vrcpilot.controls import keyboard as keyboard_mod
from vrcpilot.controls.keyboard.base import Key, Keyboard


@pytest.fixture(autouse=True)
def _reset_keyboard_singleton() -> Iterator[None]:
    """Clear the module-level lazy backend before and after each test."""
    keyboard_mod._instance = None
    yield
    keyboard_mod._instance = None


class _RecordingKeyboard(Keyboard):
    """Concrete :class:`Keyboard` that records ``(method, kwargs)`` calls.

    Distinct from :class:`tests.helpers.ImplKeyboard`: that fixture
    records ``_do_down`` / ``_do_up`` (the ABC's leaves), whereas the
    module-level dispatch tests need to assert which **public** method
    was invoked. The class overrides the public methods directly so
    the forwarded arguments are observable without re-running the
    template method.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    @override
    def press(
        self,
        *keys: Key,
        duration: float = 0.1,
        focus: bool = True,
        pid: int | None = None,
    ) -> None:
        self.calls.append(
            (
                "press",
                {"keys": keys, "duration": duration, "focus": focus, "pid": pid},
            )
        )

    @override
    def down(self, *keys: Key, focus: bool = True, pid: int | None = None) -> None:
        self.calls.append(("down", {"keys": keys, "focus": focus, "pid": pid}))

    @override
    def up(self, *keys: Key, focus: bool = True, pid: int | None = None) -> None:
        self.calls.append(("up", {"keys": keys, "focus": focus, "pid": pid}))

    @override
    def _do_down(self, key: Key) -> None:  # pragma: no cover - unused
        raise AssertionError("public methods are overridden; _do_* must not run")

    @override
    def _do_up(self, key: Key) -> None:  # pragma: no cover - unused
        raise AssertionError("public methods are overridden; _do_* must not run")


class TestLazySingleton:
    """``_get()`` caches the backend after first construction."""

    def test_returns_cached_instance_after_first_call(self) -> None:
        # Pre-populate the singleton so the test stays portable across
        # platforms (no inputtino / pydirectinput required at import).
        backend = _RecordingKeyboard()
        keyboard_mod._instance = backend

        assert keyboard_mod._get() is backend
        assert keyboard_mod._get() is backend


class TestModuleFunctionForwarding:
    """``press`` / ``down`` / ``up`` forward through ``_get()``.

    Each module-level helper is a one-line wrapper that passes
    ``*args`` and ``**kwargs`` to the corresponding method on the
    backend. The contract is "forward without reshape", verified by
    assertion on the recorded call.
    """

    def test_press_forwards_single_key(self) -> None:
        backend = _RecordingKeyboard()
        keyboard_mod._instance = backend

        keyboard_mod.press(Key.A, duration=0.05, focus=False, pid=9999)

        assert backend.calls == [
            (
                "press",
                {
                    "keys": (Key.A,),
                    "duration": 0.05,
                    "focus": False,
                    "pid": 9999,
                },
            )
        ]

    def test_press_forwards_combo_with_defaults(self) -> None:
        backend = _RecordingKeyboard()
        keyboard_mod._instance = backend

        keyboard_mod.press(Key.CTRL_LEFT, Key.C)

        assert backend.calls == [
            (
                "press",
                {
                    "keys": (Key.CTRL_LEFT, Key.C),
                    "duration": 0.1,
                    "focus": True,
                    "pid": None,
                },
            )
        ]

    def test_down_forwards_single_key(self) -> None:
        backend = _RecordingKeyboard()
        keyboard_mod._instance = backend

        keyboard_mod.down(Key.CTRL_LEFT)

        assert backend.calls == [
            ("down", {"keys": (Key.CTRL_LEFT,), "focus": True, "pid": None})
        ]

    def test_down_forwards_combo_with_pid(self) -> None:
        backend = _RecordingKeyboard()
        keyboard_mod._instance = backend

        keyboard_mod.down(Key.CTRL_LEFT, Key.SHIFT_LEFT, Key.A, pid=9999)

        assert backend.calls == [
            (
                "down",
                {
                    "keys": (Key.CTRL_LEFT, Key.SHIFT_LEFT, Key.A),
                    "focus": True,
                    "pid": 9999,
                },
            )
        ]

    def test_up_forwards_with_focus_false(self) -> None:
        backend = _RecordingKeyboard()
        keyboard_mod._instance = backend

        keyboard_mod.up(Key.CTRL_LEFT, focus=False)

        assert backend.calls == [
            ("up", {"keys": (Key.CTRL_LEFT,), "focus": False, "pid": None})
        ]
