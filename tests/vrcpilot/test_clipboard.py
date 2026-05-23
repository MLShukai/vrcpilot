"""Tests for :mod:`vrcpilot.clipboard`.

`paste` is a 4-step pipeline: ``ensure_target(pid=pid)`` (only when
``focus=True``) -> ``pyperclip.copy`` ->
``time.sleep(_CLIPBOARD_SETTLE)`` -> ``keyboard.press(Key.CTRL, Key.V,
focus=False, pid=pid)``. The tests below verify each step, the call
ordering, and that the ``focus`` / ``pid`` parameters are forwarded
correctly. ``focus=False`` is the hot-loop fast path and intentionally
skips every PID lookup (no ``ensure_target``, no internal
``resolve_pid``).

The keyboard backend is swapped via :class:`tests.helpers.ImplKeyboard`
through the lazy-singleton ``vrcpilot.controls.keyboard._get`` so the
real :class:`vrcpilot.controls.keyboard.Keyboard` template method
(focus guard, key sequencing) runs end-to-end. Only ``pyperclip``,
``time.sleep``, and ``ensure_target`` are mocked.
"""

from __future__ import annotations

import pyperclip
import pytest
from pytest_mock import MockerFixture

from tests.helpers import ImplKeyboard
from vrcpilot import clipboard
from vrcpilot.controls.keyboard import Key


@pytest.fixture
def fake_keyboard(mocker: MockerFixture) -> ImplKeyboard:
    """Wire the public ``keyboard`` module to a recording
    :class:`ImplKeyboard`.

    Does NOT stub ``ensure_target`` -- individual tests patch it as
    needed so they can spy on focus-guard behaviour.
    """
    impl = ImplKeyboard()
    mocker.patch("vrcpilot.controls.keyboard._get", return_value=impl)
    return impl


class TestPasteCopiesText:
    @pytest.mark.parametrize(
        "text",
        [
            "hello",
            "",
            "こんにちは VRChat",
            "mixed ASCII and 漢字 123",
            "改行\n含む",
        ],
    )
    def test_pyperclip_copy_called_once_with_text(
        self,
        fake_keyboard: ImplKeyboard,
        mocker: MockerFixture,
        text: str,
    ):
        del fake_keyboard
        mocker.patch("vrcpilot.clipboard.ensure_target")
        copy_spy = mocker.patch("vrcpilot.clipboard.pyperclip.copy")

        clipboard.paste(text)

        copy_spy.assert_called_once_with(text)


class TestPasteCallOrder:
    def test_ensure_target_then_copy_then_sleep_then_press(
        self, fake_keyboard: ImplKeyboard, mocker: MockerFixture
    ):
        # Record the global call order across every side-effecting API
        # by funnelling each into a single MagicMock via `attach_mock` --
        # mock_calls then preserves chronological order. ``ensure_target``
        # runs first (focus=True default), then copy, then the
        # _CLIPBOARD_SETTLE sleep, then the Ctrl+V keystroke (which is
        # dispatched with focus=False so the keyboard backend does NOT
        # run ensure_target a second time). The keyboard.press's own
        # hold-sleep follows.
        recorder = mocker.MagicMock()
        recorder.attach_mock(
            mocker.patch("vrcpilot.clipboard.ensure_target"), "ensure_target"
        )
        recorder.attach_mock(mocker.patch("vrcpilot.clipboard.pyperclip.copy"), "copy")
        recorder.attach_mock(mocker.patch("vrcpilot.clipboard.time.sleep"), "sleep")
        # Wrap the ImplKeyboard methods so they show up in the same
        # recorder timeline as copy / sleep, while still appending to
        # ``ImplKeyboard.calls``.
        recorder.attach_mock(
            mocker.patch.object(
                fake_keyboard, "_do_down", wraps=fake_keyboard._do_down
            ),
            "do_down",
        )
        recorder.attach_mock(
            mocker.patch.object(fake_keyboard, "_do_up", wraps=fake_keyboard._do_up),
            "do_up",
        )

        clipboard.paste("hi")

        # Expected order:
        #   ensure_target(pid=None)         <- step 1, focus guard
        #   copy("hi")                      <- step 2
        #   sleep(_CLIPBOARD_SETTLE)        <- step 3, paste's settle
        #   _do_down(CTRL), _do_down(V)
        #   sleep(0.1)                      <- keyboard.press hold
        #   _do_up(V), _do_up(CTRL)
        names = [c[0] for c in recorder.mock_calls]
        assert names == [
            "ensure_target",
            "copy",
            "sleep",
            "do_down",
            "do_down",
            "sleep",
            "do_up",
            "do_up",
        ]
        _, copy_call, settle_sleep, _, _, hold_sleep, _, _ = recorder.mock_calls
        assert copy_call.args == ("hi",)
        assert settle_sleep.args == (clipboard._CLIPBOARD_SETTLE,)
        assert hold_sleep.args == (0.1,)
        # And the keystroke decomposition lands after the settle.
        assert fake_keyboard.calls == [
            ("_do_down", {"key": Key.CTRL}),
            ("_do_down", {"key": Key.V}),
            ("_do_up", {"key": Key.V}),
            ("_do_up", {"key": Key.CTRL}),
        ]


class TestPasteFocusForwarding:
    def test_focus_true_invokes_ensure_target_once(
        self, fake_keyboard: ImplKeyboard, mocker: MockerFixture
    ):
        # Focus guard runs once at the top of paste; the internal
        # keyboard.press uses focus=False, so the keyboard ABC must
        # NOT invoke ensure_target again.
        del fake_keyboard
        mocker.patch("vrcpilot.clipboard.pyperclip.copy")
        mocker.patch("vrcpilot.clipboard.time.sleep")
        clipboard_guard = mocker.patch("vrcpilot.clipboard.ensure_target")
        keyboard_guard = mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")

        clipboard.paste("hi")  # default focus=True

        clipboard_guard.assert_called_once_with(pid=None)
        keyboard_guard.assert_not_called()

    def test_focus_false_skips_ensure_target(
        self, fake_keyboard: ImplKeyboard, mocker: MockerFixture
    ):
        del fake_keyboard
        mocker.patch("vrcpilot.clipboard.pyperclip.copy")
        mocker.patch("vrcpilot.clipboard.time.sleep")
        clipboard_guard = mocker.patch("vrcpilot.clipboard.ensure_target")
        keyboard_guard = mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")

        clipboard.paste("hi", focus=False)

        clipboard_guard.assert_not_called()
        keyboard_guard.assert_not_called()

    def test_focus_false_does_not_call_resolve_pid(
        self, fake_keyboard: ImplKeyboard, mocker: MockerFixture
    ):
        # Hot-loop guarantee: paste(focus=False) must not trigger a
        # psutil.process_iter scan. Patch process.resolve_pid at the
        # canonical path so any indirect call would surface.
        del fake_keyboard
        mocker.patch("vrcpilot.clipboard.pyperclip.copy")
        mocker.patch("vrcpilot.clipboard.time.sleep")
        resolve_spy = mocker.patch("vrcpilot.process.resolve_pid")

        clipboard.paste("hi", focus=False)

        resolve_spy.assert_not_called()


class TestPastePidForwarding:
    def test_pid_passed_to_ensure_target(
        self, fake_keyboard: ImplKeyboard, mocker: MockerFixture
    ):
        del fake_keyboard
        mocker.patch("vrcpilot.clipboard.pyperclip.copy")
        mocker.patch("vrcpilot.clipboard.time.sleep")
        clipboard_guard = mocker.patch("vrcpilot.clipboard.ensure_target")
        mocker.patch("vrcpilot.controls.keyboard.base.ensure_target")

        clipboard.paste("hi", pid=12345)

        clipboard_guard.assert_called_once_with(pid=12345)


class TestPasteErrorPropagation:
    def test_pyperclip_exception_propagates(
        self, fake_keyboard: ImplKeyboard, mocker: MockerFixture
    ):
        # When pyperclip itself fails (e.g. no xclip / xsel installed),
        # paste must NOT swallow the error -- CLI callers wrap it.
        mocker.patch("vrcpilot.clipboard.ensure_target")
        sleep_spy = mocker.patch("vrcpilot.clipboard.time.sleep")
        mocker.patch(
            "vrcpilot.clipboard.pyperclip.copy",
            side_effect=pyperclip.PyperclipException("no clipboard backend"),
        )

        with pytest.raises(pyperclip.PyperclipException, match="no clipboard backend"):
            clipboard.paste("hi")

        # Failure happened in step 2 (copy): sleep / keyboard must not
        # have run.
        sleep_spy.assert_not_called()
        assert fake_keyboard.calls == []
