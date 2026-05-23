"""Tests for :mod:`vrcpilot.controls.mouse`.

The test file is organised around the three layers the module exposes:

* :class:`Mouse` ABC template-method wiring -- runs on every platform
  via :class:`tests.helpers.ImplMouse` so the guard plumbing is
  verified independently of any backend. Patches target
  :mod:`vrcpilot.controls.mouse.base` because that is where
  ``ensure_target``, ``time``, and ``get_vrchat_window_rect`` are bound
  on the production code.
* :class:`vrcpilot.controls.mouse.linux.LinuxMouse` -- the
  inputtino-backed concrete class. Linux-only, with the real
  ``inputtino.Mouse`` and ``mss.mss`` swapped out via ``mocker.patch``
  so no uinput device is ever opened during testing.
* The lazy-singleton ``_get`` and the ``move`` / ``click`` / ``press``
  / ``release`` / ``scroll`` module functions, which simply forward to
  the backend.

The autouse ``_reset_mouse_singleton`` fixture clears
``vrcpilot.controls.mouse._instance`` between tests so backend
construction order does not leak between cases.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import override

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeInputtinoMouse, FakePyDirectInput
from tests.helpers import ImplMouse, only_linux, only_windows
from vrcpilot.controls import mouse as mouse_mod
from vrcpilot.controls.mouse import Mouse, MouseButton
from vrcpilot.process import VRChatNotRunningError


@pytest.fixture(autouse=True)
def _reset_mouse_singleton() -> Iterator[None]:
    """Clear the module-level lazy backend before and after each test."""
    mouse_mod._instance = None
    yield
    mouse_mod._instance = None


# --- MouseButton enum tests -----------------------------------------------


class TestMouseButton:
    """Verify the :class:`MouseButton` StrEnum contract.

    The CLI plumbing (``argparse(type=MouseButton)``) and pydirectinput
    interop both rely on the StrEnum semantics being preserved here.
    """

    def test_members_have_expected_values(self):
        assert MouseButton.LEFT.value == "left"
        assert MouseButton.RIGHT.value == "right"
        assert MouseButton.MIDDLE.value == "middle"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("left", MouseButton.LEFT),
            ("right", MouseButton.RIGHT),
            ("middle", MouseButton.MIDDLE),
        ],
    )
    def test_value_lookup_returns_singleton_member(
        self, raw: str, expected: MouseButton
    ):
        # MouseButton("left") must return the LEFT singleton, not a
        # fresh instance — argparse(type=MouseButton) relies on this.
        assert MouseButton(raw) is expected

    def test_member_compares_equal_to_its_string_value(self):
        # StrEnum equality with the underlying str is the property the
        # CLI parser leans on when comparing user input.
        assert MouseButton.LEFT == "left"
        assert MouseButton.RIGHT == "right"
        assert MouseButton.MIDDLE == "middle"

    def test_invalid_value_raises_value_error(self):
        with pytest.raises(ValueError):
            MouseButton("center")


# --- ABC template-method tests (cross-platform) ---------------------------


class TestMouseGuardWiring:
    """Verify the ABC runs ``ensure_target`` exactly when ``focus`` allows.

    Uses the real :class:`ImplMouse` (not a mock) so the abstract
    method dispatch and kwarg forwarding are exercised; only
    ``ensure_target`` is patched.
    """

    def test_focus_true_calls_ensure_target_for_every_method(
        self,
        mocker: MockerFixture,
        fake_vrchat_window: tuple[int, int, int, int],
    ):
        del fake_vrchat_window  # only needed so move()'s _to_desktop resolves
        guard = mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()

        impl.move(1, 2)
        impl.click()
        impl.press()
        impl.release()
        impl.scroll(1)

        assert guard.call_count == 5

    def test_focus_false_skips_ensure_target(
        self,
        mocker: MockerFixture,
        fake_vrchat_window: tuple[int, int, int, int],
    ):
        del fake_vrchat_window  # only needed so move()'s _to_desktop resolves
        guard = mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()

        impl.move(1, 2, focus=False)
        impl.click(focus=False)
        impl.press(focus=False)
        impl.release(focus=False)
        impl.scroll(1, focus=False)

        guard.assert_not_called()

    def test_move_forwards_arguments(
        self,
        mocker: MockerFixture,
        fake_vrchat_window: tuple[int, int, int, int],
    ):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()
        wx, wy, _, _ = fake_vrchat_window

        impl.move(10, 20, relative=True)
        impl.move(30, 40)  # default relative=False -> window-local

        # Relative deltas pass through; absolute coordinates are
        # translated by the window origin before reaching _do_move.
        assert impl.calls == [
            ("_do_move", {"x": 10, "y": 20, "relative": True}),
            ("_do_move", {"x": 30 + wx, "y": 40 + wy, "relative": False}),
        ]

    def test_click_single_button_decomposes_to_press_release(
        self, mocker: MockerFixture
    ):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")
        impl = ImplMouse()

        impl.click(MouseButton.RIGHT)

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.RIGHT}),
        ]
        sleep_spy.assert_not_called()

    def test_click_with_no_args_defaults_to_left(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()

        impl.click()

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]

    def test_click_combo_simultaneous(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")
        impl = ImplMouse()

        impl.click(MouseButton.LEFT, MouseButton.RIGHT, duration=0.05)

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]
        sleep_spy.assert_called_once_with(0.05)

    def test_click_with_duration_zero_skips_sleep(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")
        impl = ImplMouse()

        impl.click(MouseButton.LEFT, MouseButton.RIGHT, duration=0.0)

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]
        sleep_spy.assert_not_called()

    def test_click_count_3_runs_three_combo_cycles(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")
        impl = ImplMouse()

        impl.click(MouseButton.LEFT, MouseButton.RIGHT, count=3, duration=0.02)

        cycle = [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]
        assert impl.calls == cycle * 3
        assert sleep_spy.call_count == 3
        for call in sleep_spy.call_args_list:
            assert call.args == (0.02,)

    def test_click_count_zero_emits_nothing(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")
        impl = ImplMouse()

        impl.click(MouseButton.LEFT, MouseButton.RIGHT, count=0, duration=0.05)

        assert impl.calls == []
        sleep_spy.assert_not_called()

    def test_press_combo_left_to_right(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()

        impl.press(MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE)

        assert impl.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_press", {"button": MouseButton.MIDDLE}),
        ]

    def test_press_with_no_args_defaults_to_left(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()

        impl.press()

        assert impl.calls == [("_do_press", {"button": MouseButton.LEFT})]

    def test_release_combo_reversed(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()

        impl.release(MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE)

        # Reverse-on-release matches LIFO stack semantics; pairing
        # press(*bs) / release(*bs) cleans up in the opposite order.
        assert impl.calls == [
            ("_do_release", {"button": MouseButton.MIDDLE}),
            ("_do_release", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]

    def test_release_with_no_args_defaults_to_left(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()

        impl.release()

        assert impl.calls == [("_do_release", {"button": MouseButton.LEFT})]

    def test_focus_guard_runs_once_per_combo(self, mocker: MockerFixture):
        guard = mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        mocker.patch("vrcpilot.controls.mouse.base.time.sleep")
        impl = ImplMouse()

        impl.click(
            MouseButton.LEFT,
            MouseButton.RIGHT,
            MouseButton.MIDDLE,
            count=3,
            duration=0.01,
        )
        impl.press(MouseButton.LEFT, MouseButton.RIGHT)
        impl.release(MouseButton.LEFT, MouseButton.RIGHT)

        # 1 call per public method invocation, regardless of combo size
        # or count.
        assert guard.call_count == 3

    def test_scroll_forwards_amount(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()

        impl.scroll(-3)

        assert impl.calls == [("_do_scroll", {"amount": -3})]


# --- Window-local -> desktop translation tests ---------------------------


class TestMouseToDesktop:
    """Verify :meth:`Mouse._to_desktop` resolves window-local coordinates.

    The mapping is ``(x, y) -> (x + wx, y + wy)`` where ``(wx, wy)`` is
    the VRChat window origin. Out-of-window inputs (negative or beyond
    the window size) are intentionally not rejected because the OS
    accepts them and matches the previous desktop-absolute behaviour
    for points outside any monitor.
    """

    def test_origin_returns_window_origin(
        self, fake_vrchat_window: tuple[int, int, int, int]
    ):
        impl = ImplMouse()
        wx, wy, _, _ = fake_vrchat_window

        assert impl._to_desktop(0, 0) == (wx, wy)

    def test_positive_offsets_add_to_window_origin(
        self, fake_vrchat_window: tuple[int, int, int, int]
    ):
        impl = ImplMouse()
        wx, wy, _, _ = fake_vrchat_window

        assert impl._to_desktop(50, 30) == (wx + 50, wy + 30)

    def test_negative_offsets_do_not_raise(
        self, fake_vrchat_window: tuple[int, int, int, int]
    ):
        # Out-of-window points are passed through; the OS will clamp or
        # ignore them. The API contract is "do not raise".
        impl = ImplMouse()
        wx, wy, _, _ = fake_vrchat_window

        assert impl._to_desktop(-5, -5) == (wx - 5, wy - 5)

    def test_offsets_beyond_window_size_do_not_raise(
        self, fake_vrchat_window: tuple[int, int, int, int]
    ):
        impl = ImplMouse()
        wx, wy, _, _ = fake_vrchat_window

        assert impl._to_desktop(10000, 10000) == (wx + 10000, wy + 10000)

    def test_missing_window_raises_vrchat_not_running(self, mocker: MockerFixture):
        # No VRChat window -> _to_desktop cannot resolve an origin. The
        # ABC raises the same exception the focus guard does so callers
        # only need to catch one error.
        mocker.patch(
            "vrcpilot.controls.mouse.base.get_vrchat_window_rect", return_value=None
        )
        impl = ImplMouse()

        with pytest.raises(VRChatNotRunningError, match="VRChat window not found"):
            impl._to_desktop(0, 0)


class TestMouseMovePublicAbsolute:
    """Public :meth:`Mouse.move` (``relative=False``) is window-local.

    The default ``move(x, y)`` call now means "VRChat window-local
    pixels", so the backend ``_do_move`` must receive
    ``(x + wx, y + wy)`` (desktop-absolute) after translation. Verified
    through the real ABC plumbing via :class:`ImplMouse`.
    """

    def test_translates_to_desktop_before_backend_call(
        self,
        mocker: MockerFixture,
        fake_vrchat_window: tuple[int, int, int, int],
    ):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()
        wx, wy, _, _ = fake_vrchat_window

        impl.move(50, 30)

        assert impl.calls == [
            ("_do_move", {"x": wx + 50, "y": wy + 30, "relative": False}),
        ]

    def test_missing_window_propagates_vrchat_not_running(self, mocker: MockerFixture):
        # focus=False so we bypass ensure_target and prove the failure
        # comes from _to_desktop, not the guard.
        mocker.patch(
            "vrcpilot.controls.mouse.base.get_vrchat_window_rect", return_value=None
        )
        impl = ImplMouse()

        with pytest.raises(VRChatNotRunningError, match="VRChat window not found"):
            impl.move(10, 20, focus=False)

        # Backend must not have been called when translation failed.
        assert impl.calls == []


class TestMouseMovePublicRelative:
    """Public :meth:`Mouse.move` (``relative=True``) skips translation.

    Relative moves are mouse deltas, so the window origin is irrelevant
    and :func:`get_vrchat_window_rect` must not be consulted.
    """

    def test_does_not_call_get_vrchat_window_rect(self, mocker: MockerFixture):
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        rect_spy = mocker.patch(
            "vrcpilot.controls.mouse.base.get_vrchat_window_rect",
            # Deliberately return None: if the production code reads
            # this it would raise, which would fail the test loudly.
            return_value=None,
        )
        impl = ImplMouse()

        impl.move(50, 30, relative=True)

        rect_spy.assert_not_called()

    def test_forwards_deltas_unchanged(
        self, mocker: MockerFixture, fake_vrchat_window: tuple[int, int, int, int]
    ):
        del fake_vrchat_window  # not consulted on the relative path
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        impl = ImplMouse()

        impl.move(50, 30, relative=True)

        assert impl.calls == [
            ("_do_move", {"x": 50, "y": 30, "relative": True}),
        ]


# --- LinuxMouse tests (Linux-only) ----------------------------------------


@pytest.fixture
def fake_inputtino_mouse(mocker: MockerFixture) -> FakeInputtinoMouse:
    """Patch ``inputtino.Mouse`` with a recording fake.

    Linux-only fixture: imports ``inputtino`` to satisfy pyright at
    test discovery time but is gated by the ``only_linux`` mark on
    test classes that use it. The fake instance is also returned so
    tests can read ``.calls`` directly.
    """
    fake = FakeInputtinoMouse()
    mocker.patch("vrcpilot.controls.mouse.linux.inputtino.Mouse", return_value=fake)
    # Pin screen size so move_abs assertions are deterministic. The
    # production code calls mss.MSS() / .monitors / .close() directly
    # (no context manager), so a plain mock instance is enough.
    fake_sct = mocker.MagicMock()
    fake_sct.monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
    mocker.patch("vrcpilot.controls.mouse.linux.mss.MSS", return_value=fake_sct)
    return fake


@only_linux
class TestLinuxMouse:
    """Exercise the inputtino backend without touching ``/dev/uinput``.

    The Linux-only mark prevents collection on Windows; the
    ``fake_inputtino_mouse`` fixture replaces ``inputtino.Mouse`` and
    ``mss.mss`` so the production code runs end-to-end against a
    fake.
    """

    def test_move_relative_calls_move(self, fake_inputtino_mouse: FakeInputtinoMouse):
        from vrcpilot.controls.mouse.linux import LinuxMouse

        m = LinuxMouse()
        m._do_move(15, -7, relative=True)

        assert fake_inputtino_mouse.move_calls == [{"delta_x": 15, "delta_y": -7}]
        assert fake_inputtino_mouse.move_abs_calls == []

    def test_move_absolute_uses_screen_size_from_mss(
        self, fake_inputtino_mouse: FakeInputtinoMouse
    ):
        from vrcpilot.controls.mouse.linux import LinuxMouse

        m = LinuxMouse()
        m._do_move(960, 540, relative=False)

        assert fake_inputtino_mouse.move_abs_calls == [
            {
                "x": 960,
                "y": 540,
                "screen_width": 1920,
                "screen_height": 1080,
            }
        ]
        assert fake_inputtino_mouse.move_calls == []

    @pytest.mark.parametrize(
        "button,expected_value",
        [
            (MouseButton.LEFT, 0),
            (MouseButton.MIDDLE, 1),
            (MouseButton.RIGHT, 2),
        ],
    )
    def test_click_decomposes_to_press_release_via_abc(
        self,
        fake_inputtino_mouse: FakeInputtinoMouse,
        mocker: MockerFixture,
        button: MouseButton,
        expected_value: int,
    ):
        # Public ``click()`` now decomposes into the ABC's
        # _do_press / _do_release loop. The Linux backend has no
        # _do_click of its own, so a click() ends up as inputtino
        # press / release calls.
        from vrcpilot.controls.mouse.linux import LinuxMouse

        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        mocker.patch("vrcpilot.controls.mouse.base.time.sleep")

        m = LinuxMouse()
        m.click(button, count=3, duration=0.05)

        assert len(fake_inputtino_mouse.press_calls) == 3
        assert len(fake_inputtino_mouse.release_calls) == 3
        for call in fake_inputtino_mouse.press_calls:
            assert int(call["button"]) == expected_value  # type: ignore[arg-type]
        for call in fake_inputtino_mouse.release_calls:
            assert int(call["button"]) == expected_value  # type: ignore[arg-type]

    def test_click_count_zero_emits_nothing(
        self, fake_inputtino_mouse: FakeInputtinoMouse, mocker: MockerFixture
    ):
        from vrcpilot.controls.mouse.linux import LinuxMouse

        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")

        m = LinuxMouse()
        m.click(MouseButton.LEFT, count=0, duration=0.0)

        assert fake_inputtino_mouse.press_calls == []
        assert fake_inputtino_mouse.release_calls == []

    def test_press_maps_right_button(self, fake_inputtino_mouse: FakeInputtinoMouse):
        from vrcpilot.controls.mouse.linux import LinuxMouse

        m = LinuxMouse()
        m._do_press(MouseButton.RIGHT)

        assert len(fake_inputtino_mouse.press_calls) == 1
        assert int(fake_inputtino_mouse.press_calls[0]["button"]) == 2  # type: ignore[arg-type]

    def test_release_maps_middle_button(self, fake_inputtino_mouse: FakeInputtinoMouse):
        from vrcpilot.controls.mouse.linux import LinuxMouse

        m = LinuxMouse()
        m._do_release(MouseButton.MIDDLE)

        assert len(fake_inputtino_mouse.release_calls) == 1
        assert int(fake_inputtino_mouse.release_calls[0]["button"]) == 1  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "amount,expected_distance",
        [(2, 240), (-1, -120), (0, 0)],
    )
    def test_scroll_converts_notches_to_high_resolution_units(
        self,
        fake_inputtino_mouse: FakeInputtinoMouse,
        amount: int,
        expected_distance: int,
    ):
        from vrcpilot.controls.mouse.linux import LinuxMouse

        m = LinuxMouse()
        m._do_scroll(amount)

        assert fake_inputtino_mouse.scroll_vertical_calls == [
            {"distance": expected_distance}
        ]


# --- Win32Mouse tests (Windows-only) --------------------------------------


@pytest.fixture
def fake_pydirectinput(mocker: MockerFixture) -> FakePyDirectInput:
    """Patch the module-level ``pydirectinput`` symbol with a fake.

    Windows-only fixture: ``pydirectinput`` lives on
    :mod:`vrcpilot.controls.mouse.windows`, which is only importable
    when ``sys.platform == 'win32'``. The patch is therefore performed
    against the Windows backend submodule via ``mocker.patch.object``;
    importing the submodule at fixture body time (rather than module
    top) keeps Linux collection working.
    """
    from vrcpilot.controls.mouse import windows as mouse_windows

    fake = FakePyDirectInput()
    mocker.patch.object(mouse_windows, "pydirectinput", fake)
    return fake


@only_windows
class TestWin32Mouse:
    """Exercise the pydirectinput backend without touching real ``SendInput``.

    The Windows-only mark prevents collection on Linux; the
    ``fake_pydirectinput`` fixture replaces the module-level
    ``pydirectinput`` symbol so the production code runs end-to-end
    against a fake.
    """

    def test_move_absolute_calls_move_to(self, fake_pydirectinput: FakePyDirectInput):
        from vrcpilot.controls.mouse.windows import Win32Mouse

        m = Win32Mouse()
        m._do_move(100, 200, relative=False)

        assert fake_pydirectinput.move_to_calls == [{"x": 100, "y": 200}]
        assert fake_pydirectinput.move_rel_calls == []

    def test_move_relative_calls_move_rel(self, fake_pydirectinput: FakePyDirectInput):
        from vrcpilot.controls.mouse.windows import Win32Mouse

        m = Win32Mouse()
        m._do_move(15, -7, relative=True)

        assert fake_pydirectinput.move_rel_calls == [{"x": 15, "y": -7}]
        assert fake_pydirectinput.move_to_calls == []

    @pytest.mark.parametrize(
        "button", [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE]
    )
    @pytest.mark.parametrize("count", [1, 3])
    def test_click_zero_duration_decomposes_to_down_up(
        self,
        fake_pydirectinput: FakePyDirectInput,
        mocker: MockerFixture,
        button: MouseButton,
        count: int,
    ):
        # Public ``click()`` now flows through _do_press / _do_release.
        # On Win32 those resolve to ``mouseDown`` / ``mouseUp`` calls;
        # the legacy ``click()`` shortcut on pydirectinput is gone.
        from vrcpilot.controls.mouse.windows import Win32Mouse

        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")

        m = Win32Mouse()
        m.click(button, count=count, duration=0.0)

        assert fake_pydirectinput.click_calls == []
        assert fake_pydirectinput.mouse_down_calls == [{"button": button.value}] * count
        assert fake_pydirectinput.mouse_up_calls == [{"button": button.value}] * count
        sleep_spy.assert_not_called()

    def test_click_with_duration_decomposes_to_down_sleep_up(
        self,
        fake_pydirectinput: FakePyDirectInput,
        mocker: MockerFixture,
    ):
        from vrcpilot.controls.mouse.windows import Win32Mouse

        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")

        m = Win32Mouse()
        m.click(MouseButton.LEFT, count=2, duration=0.05)

        assert fake_pydirectinput.click_calls == []
        assert fake_pydirectinput.mouse_down_calls == [{"button": "left"}] * 2
        assert fake_pydirectinput.mouse_up_calls == [{"button": "left"}] * 2
        # Interleaved: down -> sleep -> up -> down -> sleep -> up.
        assert [name for name, _ in fake_pydirectinput.calls] == [
            "mouseDown",
            "mouseUp",
            "mouseDown",
            "mouseUp",
        ]
        assert sleep_spy.call_count == 2
        for call in sleep_spy.call_args_list:
            assert call.args == (0.05,)

    def test_click_combo_simultaneous(
        self,
        fake_pydirectinput: FakePyDirectInput,
        mocker: MockerFixture,
    ):
        from vrcpilot.controls.mouse.windows import Win32Mouse

        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")

        m = Win32Mouse()
        m.click(MouseButton.LEFT, MouseButton.RIGHT, duration=0.05)

        assert [name for name, _ in fake_pydirectinput.calls] == [
            "mouseDown",
            "mouseDown",
            "mouseUp",
            "mouseUp",
        ]
        assert fake_pydirectinput.mouse_down_calls == [
            {"button": "left"},
            {"button": "right"},
        ]
        # Reverse-on-release: right released before left.
        assert fake_pydirectinput.mouse_up_calls == [
            {"button": "right"},
            {"button": "left"},
        ]
        sleep_spy.assert_called_once_with(0.05)

    def test_click_count_zero_emits_nothing(
        self, fake_pydirectinput: FakePyDirectInput, mocker: MockerFixture
    ):
        from vrcpilot.controls.mouse.windows import Win32Mouse

        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")

        m = Win32Mouse()
        m.click(MouseButton.LEFT, count=0, duration=0.0)

        assert fake_pydirectinput.calls == []

    @pytest.mark.parametrize(
        "button", [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE]
    )
    def test_press_routes_to_mouse_down(
        self, fake_pydirectinput: FakePyDirectInput, button: MouseButton
    ):
        from vrcpilot.controls.mouse.windows import Win32Mouse

        m = Win32Mouse()
        m._do_press(button)

        assert fake_pydirectinput.mouse_down_calls == [{"button": button.value}]
        assert fake_pydirectinput.mouse_up_calls == []

    @pytest.mark.parametrize(
        "button", [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE]
    )
    def test_release_routes_to_mouse_up(
        self, fake_pydirectinput: FakePyDirectInput, button: MouseButton
    ):
        from vrcpilot.controls.mouse.windows import Win32Mouse

        m = Win32Mouse()
        m._do_release(button)

        assert fake_pydirectinput.mouse_up_calls == [{"button": button.value}]
        assert fake_pydirectinput.mouse_down_calls == []

    @pytest.mark.parametrize(
        "amount,expected_wheel_arg",
        [(2, -2), (-3, 3), (0, 0)],
    )
    def test_scroll_sign_flips_for_win32_wheel_convention(
        self,
        mocker: MockerFixture,
        amount: int,
        expected_wheel_arg: int,
    ):
        from vrcpilot.controls.mouse import windows as mouse_windows
        from vrcpilot.controls.mouse.windows import Win32Mouse

        # Patch the helper directly: Win32Mouse._do_scroll's sole
        # responsibility is the sign flip. The helper itself wraps
        # SendInput, which is verified separately by exercising the
        # real Win32 path in the e2e scenario.
        scroll_spy = mocker.patch.object(mouse_windows, "_scroll_wheel")

        m = Win32Mouse()
        m._do_scroll(amount)

        scroll_spy.assert_called_once_with(expected_wheel_arg)


# --- _get() lazy-init tests ----------------------------------------------


class TestGetLazyInit:
    """The backend should be created on first access and reused after."""

    def test_returns_same_instance_on_repeated_calls(self, mocker: MockerFixture):
        # Replace the backend with a recording impl so the test runs
        # on every platform without needing inputtino or pydirectinput.
        mocker.patch("vrcpilot.controls.mouse.base.ensure_target")
        instance = ImplMouse()
        mouse_mod._instance = instance

        assert mouse_mod._get() is instance
        assert mouse_mod._get() is instance

    def test_unsupported_platform_raises_not_implemented(self, mocker: MockerFixture):
        # Force the "neither linux nor win32" branch by patching the
        # module-level sys.platform reference. Singleton has been
        # cleared by the autouse fixture, so the branch is reached.
        mocker.patch.object(sys, "platform", "freebsd")

        with pytest.raises(NotImplementedError, match="freebsd"):
            mouse_mod._get()


# --- Module function delegation tests -------------------------------------


class _SpyMouse(Mouse):
    """Backend that records the public-API call it received.

    Distinct from :class:`ImplMouse` because we want to assert which
    *public* method on the backend was called -- the module functions
    forward through the public method (which then runs the guard and
    delegates to ``_do_*``), not directly to ``_do_*``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    @override
    def move(
        self, x: int, y: int, *, relative: bool = False, focus: bool = True
    ) -> None:
        self.calls.append(
            (
                "move",
                {"x": x, "y": y, "relative": relative, "focus": focus},
            )
        )

    @override
    def click(
        self,
        *buttons: MouseButton,
        count: int = 1,
        duration: float = 0.0,
        focus: bool = True,
    ) -> None:
        self.calls.append(
            (
                "click",
                {
                    "buttons": buttons,
                    "count": count,
                    "duration": duration,
                    "focus": focus,
                },
            )
        )

    @override
    def press(
        self,
        *buttons: MouseButton,
        focus: bool = True,
    ) -> None:
        self.calls.append(("press", {"buttons": buttons, "focus": focus}))

    @override
    def release(
        self,
        *buttons: MouseButton,
        focus: bool = True,
    ) -> None:
        self.calls.append(("release", {"buttons": buttons, "focus": focus}))

    @override
    def scroll(self, amount: int, *, focus: bool = True) -> None:
        self.calls.append(("scroll", {"amount": amount, "focus": focus}))

    @override
    def _do_move(self, x: int, y: int, *, relative: bool) -> None:
        # Not exercised; the spy overrides the public methods directly.
        ...

    @override
    def _do_press(self, button: MouseButton) -> None: ...

    @override
    def _do_release(self, button: MouseButton) -> None: ...

    @override
    def _do_scroll(self, amount: int) -> None: ...


class TestModuleFunctions:
    """``move`` / ``click`` / ...

    must forward through ``_get()``.
    """

    def test_move_forwards(self):
        spy = _SpyMouse()
        mouse_mod._instance = spy

        mouse_mod.move(100, 200, relative=True, focus=False)

        assert spy.calls == [
            (
                "move",
                {"x": 100, "y": 200, "relative": True, "focus": False},
            )
        ]

    def test_click_forwards(self):
        spy = _SpyMouse()
        mouse_mod._instance = spy

        mouse_mod.click(MouseButton.RIGHT, count=2, duration=0.1, focus=False)

        assert spy.calls == [
            (
                "click",
                {
                    "buttons": (MouseButton.RIGHT,),
                    "count": 2,
                    "duration": 0.1,
                    "focus": False,
                },
            )
        ]

    def test_click_combo_forwards(self):
        spy = _SpyMouse()
        mouse_mod._instance = spy

        mouse_mod.click(MouseButton.LEFT, MouseButton.RIGHT, duration=0.05)

        assert spy.calls == [
            (
                "click",
                {
                    "buttons": (MouseButton.LEFT, MouseButton.RIGHT),
                    "count": 1,
                    "duration": 0.05,
                    "focus": True,
                },
            )
        ]

    def test_press_release_forward(self):
        spy = _SpyMouse()
        mouse_mod._instance = spy

        mouse_mod.press(MouseButton.MIDDLE)
        mouse_mod.release(MouseButton.MIDDLE, focus=False)

        assert spy.calls == [
            ("press", {"buttons": (MouseButton.MIDDLE,), "focus": True}),
            ("release", {"buttons": (MouseButton.MIDDLE,), "focus": False}),
        ]

    def test_press_release_combo_forward(self):
        spy = _SpyMouse()
        mouse_mod._instance = spy

        mouse_mod.press(MouseButton.LEFT, MouseButton.RIGHT)
        mouse_mod.release(MouseButton.LEFT, MouseButton.RIGHT)

        assert spy.calls == [
            (
                "press",
                {"buttons": (MouseButton.LEFT, MouseButton.RIGHT), "focus": True},
            ),
            (
                "release",
                {"buttons": (MouseButton.LEFT, MouseButton.RIGHT), "focus": True},
            ),
        ]

    def test_scroll_forwards(self):
        spy = _SpyMouse()
        mouse_mod._instance = spy

        mouse_mod.scroll(-2, focus=False)

        assert spy.calls == [("scroll", {"amount": -2, "focus": False})]
