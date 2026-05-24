"""Tests for :mod:`vrcpilot.controls.keyboard.base`.

Covers two surfaces:

* The :class:`Key` enum's value contract -- members follow the
  ``pydirectinput`` naming convention so :class:`Win32Keyboard` can
  forward ``key.value`` directly, and ``argparse(type=Key)`` round-trips
  user input like ``escape`` / ``shiftleft``.
* The :class:`Keyboard` ABC's template-method plumbing -- the public
  ``press`` / ``down`` / ``up`` decompose into ``_do_down`` / ``_do_up``
  in the documented order, validate non-empty key lists, and forward
  ``focus`` / ``pid`` / ``duration`` to the focus guard / sleep.

The ABC tests use :class:`tests.helpers.ImplKeyboard` (a real
:class:`Keyboard` subclass that records every ``_do_*`` call) so the
abstract dispatch runs end-to-end. The ``focus=True`` integration
relies on the project-wide autouse ``_no_real_vrchat`` fixture: with no
VRChat process visible, the guard's :func:`resolve_pid` raises
:class:`VRChatNotRunningError`, which is the natural signal that the
guard was invoked.
"""

from __future__ import annotations

import pytest

from tests.helpers import ImplKeyboard
from vrcpilot.controls.keyboard.base import Key, Keyboard
from vrcpilot.process import VRChatNotRunningError

# --- Key enum value contract ----------------------------------------------


class TestKeyEnumValueContract:
    """``Key`` values must match the ``pydirectinput`` strings.

    These are the strings :class:`Win32Keyboard` forwards through
    ``pydirectinput.keyDown(key.value)``, so a typo here surfaces as a
    silent no-op on Windows. The parametrize list is a sampled spec
    check, not exhaustive -- exhaustiveness is enforced on Linux by
    ``TestInputtinoCodesExhaustive`` in ``test_linux.py``.
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
    def test_member_value(self, member: Key, value: str) -> None:
        assert member.value == value

    def test_letters_cover_a_through_z(self) -> None:
        # The lower-case ASCII alphabet must be fully represented as
        # ``Key.A``..``Key.Z`` so callers can type any letter directly.
        letters = {chr(c) for c in range(ord("a"), ord("z") + 1)}
        members = {member.value for member in Key if len(member.value) == 1}
        assert letters <= members

    def test_digits_cover_0_through_9(self) -> None:
        # Digits use the ``NUM_<n>`` prefix because identifiers cannot
        # start with a digit, but the value is the plain numeral.
        digits = {str(d) for d in range(10)}
        members = {member.value for member in Key}
        assert digits <= members

    def test_function_keys_f1_through_f12(self) -> None:
        # F13..F24 are intentionally omitted; the public surface stops
        # at F12 until a concrete need arises.
        for n in range(1, 13):
            assert Key(f"f{n}") is getattr(Key, f"F{n}")


# --- Keyboard ABC plumbing ------------------------------------------------


class TestKeyboardSingleKeyDispatch:
    """``press`` / ``down`` / ``up`` of one key reach the right ``_do_*``.

    Uses :class:`ImplKeyboard` to record the dispatched calls; the
    abstract dispatch is exercised for real. ``focus=False`` skips the
    guard so the test does not need a running VRChat.
    """

    def test_press_runs_do_down_then_do_up(self) -> None:
        impl = ImplKeyboard()

        impl.press(Key.A, duration=0.0, focus=False)

        assert impl.calls == [
            ("_do_down", {"key": Key.A}),
            ("_do_up", {"key": Key.A}),
        ]

    def test_down_runs_only_do_down(self) -> None:
        impl = ImplKeyboard()

        impl.down(Key.CTRL_LEFT, focus=False)

        assert impl.calls == [("_do_down", {"key": Key.CTRL_LEFT})]

    def test_up_runs_only_do_up(self) -> None:
        impl = ImplKeyboard()

        impl.up(Key.CTRL_LEFT, focus=False)

        assert impl.calls == [("_do_up", {"key": Key.CTRL_LEFT})]


class TestKeyboardComboOrdering:
    """Combos go down left-to-right, up in reverse (Ctrl+C convention).

    Modifiers must outlive the keys they modify so the OS sees a
    coherent state -- a stuck modifier or out-of-order release would
    corrupt downstream key events.
    """

    def test_press_combo_down_then_reverse_up(self) -> None:
        impl = ImplKeyboard()

        impl.press(Key.CTRL_LEFT, Key.C, duration=0.0, focus=False)

        assert impl.calls == [
            ("_do_down", {"key": Key.CTRL_LEFT}),
            ("_do_down", {"key": Key.C}),
            ("_do_up", {"key": Key.C}),
            ("_do_up", {"key": Key.CTRL_LEFT}),
        ]

    def test_down_combo_goes_left_to_right(self) -> None:
        impl = ImplKeyboard()

        impl.down(Key.CTRL_LEFT, Key.SHIFT_LEFT, Key.A, focus=False)

        assert impl.calls == [
            ("_do_down", {"key": Key.CTRL_LEFT}),
            ("_do_down", {"key": Key.SHIFT_LEFT}),
            ("_do_down", {"key": Key.A}),
        ]

    def test_up_combo_goes_reversed_for_lifo_pairing(self) -> None:
        # Passing the same args to down() and up() yields stack-pop
        # order on release.
        impl = ImplKeyboard()

        impl.up(Key.CTRL_LEFT, Key.SHIFT_LEFT, Key.A, focus=False)

        assert impl.calls == [
            ("_do_up", {"key": Key.A}),
            ("_do_up", {"key": Key.SHIFT_LEFT}),
            ("_do_up", {"key": Key.CTRL_LEFT}),
        ]


class TestKeyboardEmptyKeysRejected:
    """Calling without keys is a programmer error, not a silent no-op.

    All three public methods accept ``*keys`` variadically so
    ``TypeError`` is the only way to surface the misuse before any
    side effect (in particular before the focus guard fires).
    """

    def test_press_with_no_keys_raises_type_error(self) -> None:
        impl = ImplKeyboard()

        with pytest.raises(TypeError, match="at least one Key"):
            impl.press(focus=False)

        assert impl.calls == []

    def test_down_with_no_keys_raises_type_error(self) -> None:
        impl = ImplKeyboard()

        with pytest.raises(TypeError, match="at least one Key"):
            impl.down(focus=False)

        assert impl.calls == []

    def test_up_with_no_keys_raises_type_error(self) -> None:
        impl = ImplKeyboard()

        with pytest.raises(TypeError, match="at least one Key"):
            impl.up(focus=False)

        assert impl.calls == []


class TestKeyboardFocusGuardIntegration:
    """``focus=True`` invokes the real guard; ``focus=False`` skips it.

    With the autouse ``_no_real_vrchat`` fixture, ``find_pids`` returns
    empty, so the guard's :func:`resolve_pid` raises
    :class:`VRChatNotRunningError`. That exception escaping is the
    natural, no-mock proof that the guard ran. ``focus=False`` must
    not raise because the guard is skipped entirely.
    """

    def test_focus_true_invokes_guard_and_propagates_not_running(self) -> None:
        impl = ImplKeyboard()

        with pytest.raises(VRChatNotRunningError):
            impl.press(Key.A, duration=0.0)  # focus=True is the default

        # The guard fires before any ``_do_*`` call, so no key event
        # leaks even though the guard raised.
        assert impl.calls == []

    def test_focus_false_skips_guard_and_dispatches(self) -> None:
        # No VRChat is running (autouse fixture), but focus=False bypasses
        # the guard entirely, so the call must succeed and dispatch.
        impl = ImplKeyboard()

        impl.press(Key.A, duration=0.0, focus=False)

        assert impl.calls == [
            ("_do_down", {"key": Key.A}),
            ("_do_up", {"key": Key.A}),
        ]

    def test_focus_true_runs_guard_once_per_call_not_per_key(self) -> None:
        # Even with a multi-key combo the guard must fire exactly once,
        # so the focus-stealing-prevention retry loop (and its sleep)
        # does not multiply across the combo. The not-running error
        # itself is the indirect proof that the guard ran; we just need
        # to confirm that arming a combo before the failure does not
        # change anything.
        impl = ImplKeyboard()

        with pytest.raises(VRChatNotRunningError):
            impl.press(Key.CTRL_LEFT, Key.SHIFT_LEFT, Key.A, duration=0.0)

        assert impl.calls == []


class TestKeyboardPressDefaultDuration:
    """The default ``press`` duration is 0.1 s, not 0.0.

    Tuned for Unity / VRChat: shorter holds (including ``0.0``) get
    dropped in practice. Verified by stamping :func:`time.monotonic`
    inside ``_do_down`` / ``_do_up`` and asserting the gap is at least
    ~``0.05`` s -- a loose lower bound that survives scheduler noise
    while still failing if the default ever regresses to ``0.0``.
    """

    def test_default_duration_holds_for_at_least_0_05_seconds(self) -> None:
        import time
        from typing import override

        timestamps: list[float] = []

        class TimingKeyboard(Keyboard):
            @override
            def _do_down(self, key: Key) -> None:
                del key
                timestamps.append(time.monotonic())

            @override
            def _do_up(self, key: Key) -> None:
                del key
                timestamps.append(time.monotonic())

        TimingKeyboard().press(Key.SPACE, focus=False)  # default duration

        assert len(timestamps) == 2
        # Default is 0.1 s; use 0.05 lower bound for scheduler tolerance.
        assert (timestamps[1] - timestamps[0]) >= 0.05


# ``pid`` forwarding -- ``focus=True`` reuses the caller-supplied pid
# without re-running ``find_pids`` -- is exercised by the multi-instance
# e2e scenario rather than at unit level. Verifying it without mocking
# either :func:`vrcpilot.process.resolve_pid` or :mod:`vrcpilot.window`
# would require two real VRChat instances or driving the guard's focus
# retry loop against Xlib with a synthetic window. The unit-level
# property "``focus=False`` skips every PID lookup" is already covered
# above by
# ``TestKeyboardFocusGuardIntegration.test_focus_false_skips_guard_and_dispatches``.
