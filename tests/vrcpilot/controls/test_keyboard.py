"""Tests for :mod:`vrcpilot.controls.keyboard`.

Mirrors the layout of :mod:`tests.vrcpilot.controls.test_mouse`:

* :class:`Key` enum coverage (cross-platform).
* :class:`Keyboard` ABC template-method wiring -- runs on every
  platform via :class:`tests.helpers.ImplKeyboard` so the guard
  plumbing is verified independently of any backend. Patches target
  :mod:`vrcpilot.controls.keyboard.base` because that is where
  ``ensure_target`` and ``time`` are bound on the production code.
* ``_INPUTTINO_CODES`` exhaustiveness -- Linux-only because the
  mapping table only lives in :mod:`vrcpilot.controls.keyboard.linux`.
* :class:`vrcpilot.controls.keyboard.linux.LinuxKeyboard` -- the
  inputtino-backed concrete class. Linux-only, with the real
  ``inputtino.Keyboard`` swapped out via ``mocker.patch`` so no
  uinput device is ever opened during testing.
* The lazy-singleton ``_get`` and the ``press`` / ``down`` / ``up``
  module functions, which simply forward to the backend.

The autouse ``_reset_keyboard_singleton`` fixture clears
``vrcpilot.controls.keyboard._instance`` between tests so backend
construction order does not leak between cases.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import override

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeInputtinoKeyboard, FakePyDirectInput
from tests.helpers import ImplKeyboard, only_linux, only_windows
from vrcpilot.controls import keyboard as keyboard_mod
from vrcpilot.controls.keyboard import Key, Keyboard


@pytest.fixture(autouse=True)
def _reset_keyboard_singleton() -> Iterator[None]:
    """Clear the module-level lazy backend before and after each test."""
    keyboard_mod._instance = None
    yield
    keyboard_mod._instance = None


# --- Key enum tests (cross-platform) --------------------------------------


class TestKeyEnum:
    """``Key`` values must follow the pydirectinput naming convention.

    These tests anchor the spec §4.2 surface so a typo in any single
    member is caught here rather than as a downstream KeyError.
    """

    @pytest.mark.parametrize(
        "member,value",
        [
            (Key.A, "a"),
            (Key.Z, "z"),
            (Key.NUM_0, "0"),
            (Key.NUM_9, "9"),
            (Key.F1, "f1"),
            (Key.F12, "f12"),
            (Key.SHIFT, "shift"),
            (Key.SHIFT_LEFT, "shiftleft"),
            (Key.SHIFT_RIGHT, "shiftright"),
            (Key.CTRL_LEFT, "ctrlleft"),
            (Key.ALT_RIGHT, "altright"),
            (Key.WIN_LEFT, "winleft"),
            (Key.UP, "up"),
            (Key.PAGE_UP, "pageup"),
            (Key.ESCAPE, "escape"),
            (Key.SPACE, "space"),
            (Key.MINUS, "-"),
            (Key.EQUALS, "="),
            (Key.LBRACKET, "["),
            (Key.RBRACKET, "]"),
            (Key.BACKSLASH, "\\"),
            (Key.BACKTICK, "`"),
        ],
    )
    def test_member_value(self, member: Key, value: str):
        assert member.value == value

    def test_str_enum_equals_string(self):
        # StrEnum members compare equal to their string values, so
        # downstream consumers can treat them as plain strings.
        assert Key.A == "a"
        assert Key.ESCAPE == "escape"

    def test_letters_are_complete(self):
        letters = {chr(c) for c in range(ord("a"), ord("z") + 1)}
        members = {member.value for member in Key if len(member.value) == 1}
        assert letters <= members

    def test_digits_are_complete(self):
        digits = {str(d) for d in range(10)}
        members = {member.value for member in Key}
        assert digits <= members

    def test_function_keys_f1_to_f12(self):
        for n in range(1, 13):
            assert Key(f"f{n}") is getattr(Key, f"F{n}")


# --- _INPUTTINO_CODES exhaustiveness (Linux-only) -------------------------


@only_linux
class TestInputtinoCodes:
    """Every :class:`Key` member must appear in the inputtino mapping.

    A missing entry would surface as a ``KeyError`` at the first
    runtime call -- this test pulls the failure forward to test
    discovery time so it can never escape into production.
    """

    def test_mapping_covers_all_keys(self):
        from vrcpilot.controls.keyboard.linux import _INPUTTINO_CODES

        assert set(_INPUTTINO_CODES.keys()) == set(Key)

    def test_mapping_values_are_inputtino_keycodes(self):
        import inputtino

        from vrcpilot.controls.keyboard.linux import _INPUTTINO_CODES

        for member, code in _INPUTTINO_CODES.items():
            assert isinstance(
                code, inputtino.KeyCode
            ), f"{member!r} maps to non-KeyCode value {code!r}"

    @pytest.mark.parametrize(
        "key_name,code_name",
        [
            ("ESCAPE", "ESC"),
            ("EQUALS", "PLUS"),
            ("BACKTICK", "TILDE"),
            ("LBRACKET", "OPEN_BRACKET"),
            ("RBRACKET", "CLOSE_BRACKET"),
            ("SHIFT_LEFT", "LEFT_SHIFT"),
            ("SHIFT_RIGHT", "RIGHT_SHIFT"),
            ("CTRL_LEFT", "LEFT_CONTROL"),
            ("CTRL_RIGHT", "RIGHT_CONTROL"),
            ("ALT_LEFT", "LEFT_ALT"),
            ("ALT_RIGHT", "RIGHT_ALT"),
            ("WIN_LEFT", "LEFT_WIN"),
            ("WIN_RIGHT", "RIGHT_WIN"),
            ("NUM_0", "KEY_0"),
            ("NUM_9", "KEY_9"),
        ],
    )
    def test_known_name_translations(self, key_name: str, code_name: str):
        import inputtino

        from vrcpilot.controls.keyboard.linux import _INPUTTINO_CODES

        key = getattr(Key, key_name)
        expected = getattr(inputtino.KeyCode, code_name)
        assert _INPUTTINO_CODES[key] is expected


# --- ABC template-method tests (cross-platform) ---------------------------


class TestKeyboardGuardWiring:
    """Verify the ABC runs ``ensure_target`` exactly when ``focus`` allows.

    Uses the real :class:`ImplKeyboard` (not a mock) so the abstract
    method dispatch and kwarg forwarding are exercised; only
    ``ensure_target`` is patched.
    """

    def test_focus_true_calls_ensure_target_for_every_method(
        self, mocker: MockerFixture
    ):
        guard = mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        mocker.patch("vrcpilot.controls.keyboard.base.time.sleep")
        impl = ImplKeyboard()

        impl.press(Key.A)
        impl.down(Key.SHIFT_LEFT)
        impl.up(Key.SHIFT_LEFT)

        assert guard.call_count == 3

    def test_focus_false_skips_ensure_target(self, mocker: MockerFixture):
        guard = mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        mocker.patch("vrcpilot.controls.keyboard.base.time.sleep")
        impl = ImplKeyboard()

        impl.press(Key.A, focus=False)
        impl.down(Key.SHIFT_LEFT, focus=False)
        impl.up(Key.SHIFT_LEFT, focus=False)

        guard.assert_not_called()

    def test_press_single_key_decomposes_to_down_sleep_up(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.keyboard.base.time.sleep")
        impl = ImplKeyboard()

        impl.press(Key.A, duration=0.05)

        assert impl.calls == [
            ("_do_down", {"key": Key.A}),
            ("_do_up", {"key": Key.A}),
        ]
        sleep_spy.assert_called_once_with(0.05)

    def test_press_default_duration_is_0_1(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.keyboard.base.time.sleep")
        impl = ImplKeyboard()

        impl.press(Key.SPACE)

        sleep_spy.assert_called_once_with(0.1)

    def test_down_up_forward_key(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        impl = ImplKeyboard()

        impl.down(Key.CTRL_LEFT)
        impl.up(Key.CTRL_LEFT)

        assert impl.calls == [
            ("_do_down", {"key": Key.CTRL_LEFT}),
            ("_do_up", {"key": Key.CTRL_LEFT}),
        ]

    def test_press_combo_runs_down_left_to_right_and_up_reversed(
        self, mocker: MockerFixture
    ):
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.keyboard.base.time.sleep")
        impl = ImplKeyboard()

        impl.press(Key.CTRL_LEFT, Key.C, duration=0.05)

        assert impl.calls == [
            ("_do_down", {"key": Key.CTRL_LEFT}),
            ("_do_down", {"key": Key.C}),
            ("_do_up", {"key": Key.C}),
            ("_do_up", {"key": Key.CTRL_LEFT}),
        ]
        sleep_spy.assert_called_once_with(0.05)

    def test_down_combo_left_to_right(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        impl = ImplKeyboard()

        impl.down(Key.CTRL_LEFT, Key.SHIFT_LEFT, Key.A)

        assert impl.calls == [
            ("_do_down", {"key": Key.CTRL_LEFT}),
            ("_do_down", {"key": Key.SHIFT_LEFT}),
            ("_do_down", {"key": Key.A}),
        ]

    def test_up_combo_reversed(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        impl = ImplKeyboard()

        impl.up(Key.CTRL_LEFT, Key.SHIFT_LEFT, Key.A)

        # LIFO: same arg list passed to down + up yields stack-pop order.
        assert impl.calls == [
            ("_do_up", {"key": Key.A}),
            ("_do_up", {"key": Key.SHIFT_LEFT}),
            ("_do_up", {"key": Key.CTRL_LEFT}),
        ]

    def test_press_with_no_keys_raises_type_error(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        impl = ImplKeyboard()

        with pytest.raises(TypeError, match="at least one Key"):
            impl.press()

        assert impl.calls == []

    def test_down_with_no_keys_raises_type_error(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        impl = ImplKeyboard()

        with pytest.raises(TypeError, match="at least one Key"):
            impl.down()

        assert impl.calls == []

    def test_up_with_no_keys_raises_type_error(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        impl = ImplKeyboard()

        with pytest.raises(TypeError, match="at least one Key"):
            impl.up()

        assert impl.calls == []

    def test_focus_guard_runs_once_per_call_not_per_key(self, mocker: MockerFixture):
        guard = mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        mocker.patch("vrcpilot.controls.keyboard.base.time.sleep")
        impl = ImplKeyboard()

        impl.press(Key.A, Key.B, Key.C)

        assert guard.call_count == 1


# --- LinuxKeyboard tests (Linux-only) -------------------------------------


@pytest.fixture
def fake_inputtino_keyboard(mocker: MockerFixture) -> FakeInputtinoKeyboard:
    """Patch ``inputtino.Keyboard`` with a recording fake.

    Linux-only fixture: imports ``inputtino`` to satisfy pyright at
    test discovery time but is gated by the ``only_linux`` mark on
    test classes that use it. The fake instance is also returned so
    tests can read ``.calls`` directly.
    """
    fake = FakeInputtinoKeyboard()
    mocker.patch(
        "vrcpilot.controls.keyboard.linux.inputtino.Keyboard", return_value=fake
    )
    return fake


@only_linux
class TestLinuxKeyboard:
    """Exercise the inputtino backend without touching ``/dev/uinput``.

    The Linux-only mark prevents collection on Windows; the
    ``fake_inputtino_keyboard`` fixture replaces ``inputtino.Keyboard``
    so the production code runs end-to-end against a fake.
    """

    def test_do_down_forwards_to_press(
        self, fake_inputtino_keyboard: FakeInputtinoKeyboard
    ):
        import inputtino

        from vrcpilot.controls.keyboard.linux import LinuxKeyboard

        kb = LinuxKeyboard()
        kb._do_down(Key.SHIFT_LEFT)

        assert fake_inputtino_keyboard.press_calls == [
            {"key_code": inputtino.KeyCode.LEFT_SHIFT}
        ]

    def test_do_up_forwards_to_release(
        self, fake_inputtino_keyboard: FakeInputtinoKeyboard
    ):
        import inputtino

        from vrcpilot.controls.keyboard.linux import LinuxKeyboard

        kb = LinuxKeyboard()
        kb._do_up(Key.CTRL_RIGHT)

        assert fake_inputtino_keyboard.release_calls == [
            {"key_code": inputtino.KeyCode.RIGHT_CONTROL}
        ]

    def test_modifier_combo_sequence(
        self,
        fake_inputtino_keyboard: FakeInputtinoKeyboard,
        mocker: MockerFixture,
    ):
        # Drive the public methods so the guard is invoked, but stub
        # it out so the test does not need a running VRChat. ``press``
        # now decomposes to _do_down -> sleep -> _do_up, so the
        # backend sees only press/release calls.
        import inputtino

        from vrcpilot.controls.keyboard.linux import LinuxKeyboard

        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")
        mocker.patch("vrcpilot.controls.keyboard.base.time.sleep")
        kb = LinuxKeyboard()

        kb.down(Key.SHIFT_LEFT)
        kb.press(Key.A)
        kb.up(Key.SHIFT_LEFT)

        assert fake_inputtino_keyboard.calls == [
            ("press", {"key_code": inputtino.KeyCode.LEFT_SHIFT}),
            ("press", {"key_code": inputtino.KeyCode.A}),
            ("release", {"key_code": inputtino.KeyCode.A}),
            ("release", {"key_code": inputtino.KeyCode.LEFT_SHIFT}),
        ]


# --- Win32Keyboard tests (Windows-only) -----------------------------------


@pytest.fixture
def fake_pydirectinput(mocker: MockerFixture) -> FakePyDirectInput:
    """Patch the module-level ``pydirectinput`` symbol with a fake.

    Windows-only fixture: ``pydirectinput`` lives on
    :mod:`vrcpilot.controls.keyboard.windows`, which is only importable
    when ``sys.platform == 'win32'``. The patch is therefore performed
    against the Windows backend submodule via ``mocker.patch`` with a
    dotted string so collection on Linux does not eagerly import it.
    """
    from vrcpilot.controls.keyboard import windows as keyboard_windows

    fake = FakePyDirectInput()
    mocker.patch.object(keyboard_windows, "pydirectinput", fake)
    return fake


@only_windows
class TestWin32Keyboard:
    """Exercise the pydirectinput backend without touching real ``SendInput``.

    The Windows-only mark prevents collection on Linux; the
    ``fake_pydirectinput`` fixture replaces the module-level
    ``pydirectinput`` symbol so the production code runs end-to-end
    against a fake.
    """

    @pytest.mark.parametrize(
        "key", [Key.A, Key.SHIFT_LEFT, Key.CTRL_LEFT, Key.ALT_RIGHT]
    )
    def test_do_down_routes_to_key_down(
        self, fake_pydirectinput: FakePyDirectInput, key: Key
    ):
        from vrcpilot.controls.keyboard.windows import Win32Keyboard

        kb = Win32Keyboard()
        kb._do_down(key)

        assert fake_pydirectinput.key_down_calls == [{"key": key.value}]
        assert fake_pydirectinput.key_up_calls == []

    @pytest.mark.parametrize(
        "key", [Key.A, Key.SHIFT_LEFT, Key.CTRL_LEFT, Key.ALT_RIGHT]
    )
    def test_do_up_routes_to_key_up(
        self, fake_pydirectinput: FakePyDirectInput, key: Key
    ):
        from vrcpilot.controls.keyboard.windows import Win32Keyboard

        kb = Win32Keyboard()
        kb._do_up(key)

        assert fake_pydirectinput.key_up_calls == [{"key": key.value}]
        assert fake_pydirectinput.key_down_calls == []

    @pytest.mark.parametrize("key", list(Key))
    def test_every_key_member_reaches_pydirectinput_key_down(
        self, fake_pydirectinput: FakePyDirectInput, key: Key
    ):
        # Coverage smoke: no Key member should crash the Win32 backend
        # in unit tests. Real pydirectinput KEYBOARD_MAPPING compatibility
        # is verified by the manual smoke / e2e scenario.
        from vrcpilot.controls.keyboard.windows import Win32Keyboard

        kb = Win32Keyboard()
        kb._do_down(key)
        kb._do_up(key)

        assert fake_pydirectinput.key_down_calls == [{"key": key.value}]
        assert fake_pydirectinput.key_up_calls == [{"key": key.value}]


# --- _get() lazy-init tests ----------------------------------------------


class TestGetLazyInit:
    """The backend should be created on first access and reused after."""

    def test_returns_same_instance_on_repeated_calls(self):
        # Replace the backend with a recording impl so the test runs
        # on every platform without needing inputtino.
        instance = ImplKeyboard()
        keyboard_mod._instance = instance

        assert keyboard_mod._get() is instance
        assert keyboard_mod._get() is instance

    def test_unsupported_platform_raises_not_implemented(self, mocker: MockerFixture):
        # Force the "neither linux nor win32" branch by patching the
        # module-level sys.platform reference. Singleton has been
        # cleared by the autouse fixture, so the branch is reached.
        mocker.patch.object(sys, "platform", "freebsd")

        with pytest.raises(NotImplementedError, match="freebsd"):
            keyboard_mod._get()


# --- Module function delegation tests -------------------------------------


class _SpyKeyboard(Keyboard):
    """Backend that records the public-API call it received.

    Distinct from :class:`ImplKeyboard` because we want to assert
    which *public* method on the backend was called -- the module
    functions forward through the public method (which then runs the
    guard and delegates to ``_do_*``), not directly to ``_do_*``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    @override
    def press(self, *keys: Key, duration: float = 0.1, focus: bool = True) -> None:
        self.calls.append(
            (
                "press",
                {"keys": keys, "duration": duration, "focus": focus},
            )
        )

    @override
    def down(self, *keys: Key, focus: bool = True) -> None:
        self.calls.append(("down", {"keys": keys, "focus": focus}))

    @override
    def up(self, *keys: Key, focus: bool = True) -> None:
        self.calls.append(("up", {"keys": keys, "focus": focus}))

    @override
    def _do_down(self, key: Key) -> None: ...

    @override
    def _do_up(self, key: Key) -> None: ...


class TestModuleFunctions:
    """``press`` / ``down`` / ``up`` must forward through ``_get()``."""

    def test_press_forwards(self):
        spy = _SpyKeyboard()
        keyboard_mod._instance = spy

        keyboard_mod.press(Key.A, duration=0.05, focus=False)

        assert spy.calls == [
            ("press", {"keys": (Key.A,), "duration": 0.05, "focus": False})
        ]

    def test_press_forwards_combo(self):
        spy = _SpyKeyboard()
        keyboard_mod._instance = spy

        keyboard_mod.press(Key.CTRL_LEFT, Key.C, duration=0.2)

        assert spy.calls == [
            (
                "press",
                {
                    "keys": (Key.CTRL_LEFT, Key.C),
                    "duration": 0.2,
                    "focus": True,
                },
            )
        ]

    def test_down_forwards(self):
        spy = _SpyKeyboard()
        keyboard_mod._instance = spy

        keyboard_mod.down(Key.CTRL_LEFT)

        assert spy.calls == [("down", {"keys": (Key.CTRL_LEFT,), "focus": True})]

    def test_down_forwards_combo(self):
        spy = _SpyKeyboard()
        keyboard_mod._instance = spy

        keyboard_mod.down(Key.CTRL_LEFT, Key.SHIFT_LEFT, Key.A)

        assert spy.calls == [
            (
                "down",
                {
                    "keys": (Key.CTRL_LEFT, Key.SHIFT_LEFT, Key.A),
                    "focus": True,
                },
            )
        ]

    def test_up_forwards(self):
        spy = _SpyKeyboard()
        keyboard_mod._instance = spy

        keyboard_mod.up(Key.CTRL_LEFT, focus=False)

        assert spy.calls == [("up", {"keys": (Key.CTRL_LEFT,), "focus": False})]

    def test_up_forwards_combo(self):
        spy = _SpyKeyboard()
        keyboard_mod._instance = spy

        keyboard_mod.up(Key.CTRL_LEFT, Key.SHIFT_LEFT)

        assert spy.calls == [
            (
                "up",
                {"keys": (Key.CTRL_LEFT, Key.SHIFT_LEFT), "focus": True},
            )
        ]
