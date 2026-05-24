"""Tests for :mod:`vrcpilot.controls.mouse.base`.

Covers two surfaces:

* The :class:`MouseButton` enum's value contract -- members map to the
  lower-case strings ``pydirectinput`` and the CLI ``argparse(type=...)``
  both consume.
* The :class:`Mouse` ABC's template-method plumbing -- the public
  ``click`` / ``press`` / ``release`` / ``scroll`` decompose into
  ``_do_press`` / ``_do_release`` / ``_do_scroll`` in the documented
  order, default to :attr:`MouseButton.LEFT` when no button is given,
  honour ``count`` / ``duration``, and forward ``focus`` / ``pid``.

The :meth:`Mouse.move` absolute path translates window-local to
desktop coordinates by consulting :func:`get_vrchat_window_rect`, which
is one of vrcpilot's own functions and therefore off-limits for
mocking. Its relative-mode behaviour (no rect lookup needed) is
verified here; the absolute-mode path is exercised in
``test_linux.py`` / ``test_windows.py`` against the real geometry
helper and ultimately by ``tests/e2e/mouse.py``.

The ABC tests use :class:`tests.helpers.ImplMouse` (a real
:class:`Mouse` subclass that records every ``_do_*`` call) so the
abstract dispatch runs end-to-end. The ``focus=True`` integration
relies on the project-wide autouse ``_no_real_vrchat`` fixture: with
no VRChat process visible, the guard's :func:`resolve_pid` raises
:class:`VRChatNotRunningError`, which is the natural signal that the
guard was invoked.
"""

from __future__ import annotations

import pytest

from tests.helpers import ImplMouse
from vrcpilot.controls.mouse.base import Mouse, MouseButton
from vrcpilot.process import VRChatNotRunningError

# --- MouseButton enum contract --------------------------------------------


class TestMouseButtonEnumContract:
    """``MouseButton`` values must be the lower-case ``left`` / ``right`` /
    ``middle``.

    Verified because ``argparse(type=MouseButton)`` round-trips user
    input directly through ``MouseButton("left")`` (the StrEnum value
    lookup) and pydirectinput's mouse API consumes the same strings.
    A typo would silently break both paths.
    """

    @pytest.mark.parametrize(
        "member,value",
        [
            (MouseButton.LEFT, "left"),
            (MouseButton.RIGHT, "right"),
            (MouseButton.MIDDLE, "middle"),
        ],
    )
    def test_member_value(self, member: MouseButton, value: str) -> None:
        assert member.value == value

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("left", MouseButton.LEFT),
            ("right", MouseButton.RIGHT),
            ("middle", MouseButton.MIDDLE),
        ],
    )
    def test_value_lookup_returns_singleton(
        self, raw: str, expected: MouseButton
    ) -> None:
        # ``MouseButton("left")`` must return the canonical LEFT
        # singleton (not a new instance) -- argparse leans on this.
        assert MouseButton(raw) is expected

    def test_unknown_value_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            MouseButton("center")


# --- Mouse ABC -- click decomposition -------------------------------------


class TestMouseClickSingleButton:
    """``click(b)`` decomposes to ``_do_press(b)`` then ``_do_release(b)``.

    Empty argument list falls back to :attr:`MouseButton.LEFT` (the
    natural default for a no-argument click). ``focus=False`` skips the
    guard so the test does not need a running VRChat.
    """

    def test_explicit_button_runs_press_then_release(self) -> None:
        impl = ImplMouse()

        impl.click(MouseButton.RIGHT, focus=False)

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.RIGHT}),
        ]

    def test_no_button_defaults_to_left(self) -> None:
        impl = ImplMouse()

        impl.click(focus=False)

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]


class TestMouseClickComboOrdering:
    """Combo clicks press left-to-right, release reversed.

    Mirrors the ``Ctrl+C`` convention from :meth:`Keyboard.press` so the
    same LIFO discipline applies to multi-button gestures.
    """

    def test_two_button_combo(self) -> None:
        impl = ImplMouse()

        impl.click(MouseButton.LEFT, MouseButton.RIGHT, focus=False)

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]


class TestMouseClickCount:
    """``count`` repeats the press/release cycle exactly that many times.

    ``count=0`` is documented as "emit nothing" rather than "do a single
    cycle"; preserves the natural "no work" interpretation so callers
    can compute counts dynamically without special-casing zero.
    """

    def test_count_three_runs_three_cycles(self) -> None:
        impl = ImplMouse()

        impl.click(MouseButton.LEFT, MouseButton.RIGHT, count=3, focus=False)

        cycle = [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]
        assert impl.calls == cycle * 3

    def test_count_zero_emits_nothing(self) -> None:
        impl = ImplMouse()

        impl.click(MouseButton.LEFT, count=0, focus=False)

        assert impl.calls == []


class TestMouseClickInterval:
    """``interval`` inserts a real sleep *between* click cycles.

    The default is ``0.0`` (no sleep, full backwards compatibility with
    callers that omit the keyword). When ``interval > 0`` and
    ``count > 1`` the press of cycle *n+1* must wait at least
    ``interval`` seconds after the release of cycle *n*; intra-cycle
    ``press -> release`` is unaffected and the final cycle's release is
    not followed by another sleep. ``count <= 1`` makes ``interval``
    moot -- no cycle transitions exist -- so the call returns promptly
    even with a large ``interval``.

    Verified by stamping :func:`time.monotonic` inside ``_do_press`` /
    ``_do_release`` (a local :class:`Mouse` subclass, mirroring
    ``TestKeyboardPressDefaultDuration`` over in ``keyboard/``) and
    asserting the gap is at least roughly half the requested
    ``interval`` -- a loose lower bound that survives scheduler noise
    while still catching a regression to "no sleep at all". Upper
    bounds on real sleeps are avoided because they flake under CI host
    jitter; the "no sleep happened" tests instead bound the *whole*
    call's wall-clock to something much smaller than the would-be
    interval.
    """

    def test_interval_inserts_gap_between_cycles_only(self) -> None:
        import time
        from typing import override

        timestamps: list[tuple[str, float]] = []

        class TimingMouse(Mouse):
            @override
            def _do_press(self, button: MouseButton) -> None:
                del button
                timestamps.append(("press", time.monotonic()))

            @override
            def _do_release(self, button: MouseButton) -> None:
                del button
                timestamps.append(("release", time.monotonic()))

            @override
            def _do_move(self, x: int, y: int, *, relative: bool) -> None:
                del x, y, relative

            @override
            def _do_scroll(self, amount: int) -> None:
                del amount

        TimingMouse().click(count=3, interval=0.05, focus=False)

        # Three cycles: press/release/press/release/press/release.
        assert [kind for kind, _ in timestamps] == [
            "press",
            "release",
            "press",
            "release",
            "press",
            "release",
        ]

        # Inter-cycle gaps (release[i] -> press[i+1]) must each meet the
        # loose lower bound (~half the requested interval).
        gap_1 = timestamps[2][1] - timestamps[1][1]  # cycle 1 -> 2
        gap_2 = timestamps[4][1] - timestamps[3][1]  # cycle 2 -> 3
        assert gap_1 >= 0.025
        assert gap_2 >= 0.025

        # Intra-cycle press->release is *not* affected by ``interval``;
        # duration defaulted to 0.0 so each cycle should be near-zero.
        intra_1 = timestamps[1][1] - timestamps[0][1]
        intra_2 = timestamps[3][1] - timestamps[2][1]
        intra_3 = timestamps[5][1] - timestamps[4][1]
        assert intra_1 < 0.025
        assert intra_2 < 0.025
        assert intra_3 < 0.025

    def test_interval_default_inserts_no_sleep(self) -> None:
        import time

        impl = ImplMouse()

        start = time.monotonic()
        impl.click(count=3, focus=False)  # interval defaults to 0.0
        elapsed = time.monotonic() - start

        # Three cycles with no interval and zero duration must finish
        # essentially instantly. A real sleep would push past 0.05s.
        assert elapsed < 0.05
        # Sanity: three full cycles were emitted.
        assert len(impl.calls) == 6

    def test_count_one_ignores_interval(self) -> None:
        import time

        impl = ImplMouse()

        # A 1-second interval would dominate the elapsed time if the
        # implementation ever slept; with ``count=1`` there are no
        # cycle transitions, so no sleep should happen.
        start = time.monotonic()
        impl.click(count=1, interval=1.0, focus=False)
        elapsed = time.monotonic() - start

        assert elapsed < 0.05
        assert impl.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]

    def test_count_zero_ignores_interval(self) -> None:
        import time

        impl = ImplMouse()

        start = time.monotonic()
        impl.click(count=0, interval=1.0, focus=False)
        elapsed = time.monotonic() - start

        # ``count=0`` already means "emit nothing"; pairing it with a
        # large ``interval`` must not introduce any sleep either.
        assert elapsed < 0.05
        assert impl.calls == []

    def test_non_positive_interval_inserts_no_sleep(self) -> None:
        import time

        impl = ImplMouse()

        # Negative / zero intervals are treated as no-op, mirroring the
        # documented "interval <= 0 is no-op" semantics.
        start = time.monotonic()
        impl.click(count=3, interval=-0.5, focus=False)
        elapsed = time.monotonic() - start

        assert elapsed < 0.05
        assert len(impl.calls) == 6


# --- Mouse ABC -- press / release / scroll --------------------------------


class TestMousePressRelease:
    """``press`` / ``release`` are the half-actions of :meth:`click`.

    ``press`` goes left-to-right, ``release`` goes reversed, so passing
    the same arg list to both yields LIFO stack-pop semantics. Empty
    argument lists fall back to :attr:`MouseButton.LEFT`.
    """

    def test_press_combo_goes_left_to_right(self) -> None:
        impl = ImplMouse()

        impl.press(
            MouseButton.LEFT,
            MouseButton.RIGHT,
            MouseButton.MIDDLE,
            focus=False,
        )

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_press", {"button": MouseButton.MIDDLE}),
        ]

    def test_release_combo_goes_reversed(self) -> None:
        impl = ImplMouse()

        impl.release(
            MouseButton.LEFT,
            MouseButton.RIGHT,
            MouseButton.MIDDLE,
            focus=False,
        )

        assert impl.calls == [
            ("_do_release", {"button": MouseButton.MIDDLE}),
            ("_do_release", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]

    def test_press_empty_defaults_to_left(self) -> None:
        impl = ImplMouse()

        impl.press(focus=False)

        assert impl.calls == [("_do_press", {"button": MouseButton.LEFT})]

    def test_release_empty_defaults_to_left(self) -> None:
        impl = ImplMouse()

        impl.release(focus=False)

        assert impl.calls == [("_do_release", {"button": MouseButton.LEFT})]


class TestMouseScroll:
    """``scroll(n)`` forwards ``n`` directly to ``_do_scroll``.

    The ABC does no sign flipping or rescaling -- that is the backend's
    job (Win32 has to invert because of the platform's wheel convention,
    Linux multiplies by 120 for high-resolution units). The ABC just
    forwards the user-facing integer.
    """

    def test_positive_amount_forwarded_as_is(self) -> None:
        impl = ImplMouse()

        impl.scroll(3, focus=False)

        assert impl.calls == [("_do_scroll", {"amount": 3})]

    def test_negative_amount_forwarded_as_is(self) -> None:
        impl = ImplMouse()

        impl.scroll(-3, focus=False)

        assert impl.calls == [("_do_scroll", {"amount": -3})]


# --- Mouse ABC -- focus guard integration ---------------------------------


class TestMouseFocusGuardIntegration:
    """``focus=True`` invokes the real guard; ``focus=False`` skips it.

    Mirrors :class:`TestKeyboardFocusGuardIntegration` from
    ``test_base.py`` over in ``keyboard/``: the autouse fixture makes
    :func:`vrcpilot.process.find_pids` empty, so the guard's
    :func:`resolve_pid` raises :class:`VRChatNotRunningError`. That
    exception escaping is the natural, no-mock proof that the guard
    ran. ``focus=False`` must dispatch through to ``_do_*`` because
    the guard is skipped entirely.

    :meth:`Mouse.move` requires window geometry on the absolute path,
    so the focus integration tests use ``click`` / ``press`` /
    ``release`` / ``scroll`` (which do not consult the rect helper).
    """

    def test_focus_true_invokes_guard_and_propagates_not_running(self) -> None:
        impl = ImplMouse()

        with pytest.raises(VRChatNotRunningError):
            impl.click()  # focus=True is the default

        # Guard fires before any ``_do_*`` call.
        assert impl.calls == []

    def test_focus_false_skips_guard_and_dispatches(self) -> None:
        impl = ImplMouse()

        impl.click(focus=False)

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]


# --- Mouse ABC -- relative move (no rect lookup) -------------------------


class TestMouseMoveRelative:
    """Relative moves bypass :func:`get_vrchat_window_rect`.

    The window origin is irrelevant when ``(x, y)`` are deltas, so the
    backend's ``_do_move`` receives the raw integers unchanged and the
    rect helper is never consulted. We verify only the forwarding shape
    -- ``relative=True`` plus the unchanged ``(x, y)``.

    The absolute path is window-local and consults the real
    :func:`get_vrchat_window_rect`, which in turn opens X11 / Win32.
    That is integration territory and is covered by the backend
    test files; the ABC-level absolute test would either need a real
    VRChat window (e2e) or a mock of vrcpilot's own geometry helper
    (banned by the test policy).
    """

    def test_relative_move_forwards_deltas_unchanged(self) -> None:
        impl = ImplMouse()

        impl.move(15, -7, relative=True, focus=False)

        assert impl.calls == [
            ("_do_move", {"x": 15, "y": -7, "relative": True}),
        ]
