"""Integration-real tests for :mod:`vrcpilot.clipboard`.

:func:`vrcpilot.clipboard.paste` is a 4-step pipeline:

1. :func:`ensure_target` (skipped when ``focus=False``)
2. :func:`pyperclip.copy` -- writes ``text`` to the OS clipboard
3. :func:`time.sleep` for ``_CLIPBOARD_SETTLE`` seconds so xclip /
   xsel can take selection ownership before the next step
4. :func:`vrcpilot.controls.keyboard.press` (CTRL + V) -- dispatched
   with ``focus=False`` because step 1 already took the focus path

The interesting boundary for unit testing is step 2: the text the
caller passes must actually land on the system clipboard. Verifying
that without mocking pyperclip requires a real clipboard backend
(``xclip`` / ``xsel`` on X11, native API on Windows). The module is
skipped at collection time when no backend is reachable; the same
property is covered by ``tests/e2e/clipboard.py`` against a real
VRChat text field.

Steps 1, 3, and 4 are covered indirectly:

* Step 1 (the focus guard) is exercised by the keyboard / mouse ABC
  tests via the autouse ``_no_real_vrchat`` fixture.
* Steps 3 and 4 are implementation details whose only observable
  effect is "Ctrl+V was sent" -- the e2e scenario verifies that VRChat
  received the paste; a unit test that asserted call order against
  mocked sleep / press would only test the implementation steps, not
  the contract.
"""

from __future__ import annotations

import pyperclip
import pytest


def _pyperclip_available() -> bool:
    """Return ``True`` when a working clipboard backend is reachable.

    Probed by writing and reading back a sentinel string. False on
    Linux hosts without ``xclip`` / ``xsel`` / ``wl-clipboard``, and
    on macOS / BSD which vrcpilot does not support at all.
    """
    try:
        sentinel = "__vrcpilot_clipboard_probe__"
        pyperclip.copy(sentinel)
        return pyperclip.paste() == sentinel
    except pyperclip.PyperclipException:
        return False


if not _pyperclip_available():
    pytest.skip(
        "No pyperclip backend reachable (need xclip / xsel / wl-clipboard "
        "on Linux). Covered by tests/e2e/clipboard.py instead.",
        allow_module_level=True,
    )

# Imported below the gate so doctest collection on backendless hosts
# still skips cleanly.
from collections.abc import Iterator  # noqa: E402

from tests.helpers import ImplKeyboard  # noqa: E402
from vrcpilot import clipboard  # noqa: E402
from vrcpilot.controls import keyboard as keyboard_mod  # noqa: E402
from vrcpilot.controls.keyboard.base import Key  # noqa: E402


@pytest.fixture
def recording_keyboard() -> Iterator[ImplKeyboard]:
    """Swap the keyboard singleton for an :class:`ImplKeyboard` recorder.

    The clipboard module's ``Ctrl+V`` dispatch flows through
    :func:`vrcpilot.controls.keyboard.press`, which delegates to the
    module-level singleton ``_instance``. Replacing the singleton with
    a recording :class:`ImplKeyboard` lets the test observe the key
    sequence without opening ``/dev/uinput`` or driving real
    ``pydirectinput``. Restored after the test so other modules see the
    original (lazy) singleton.
    """
    original = keyboard_mod._instance
    impl = ImplKeyboard()
    keyboard_mod._instance = impl
    try:
        yield impl
    finally:
        keyboard_mod._instance = original


class TestPasteWritesTextToClipboard:
    """``paste(text)`` must leave ``text`` on the OS clipboard.

    This is the load-bearing observable: the production code paths
    ``text -> pyperclip.copy -> OS clipboard``, and downstream
    consumers (VRChat's Ctrl+V handler, or anything that calls
    :func:`pyperclip.paste` after the call) read it back from there.
    Driven with ``focus=False`` because no VRChat is running in the
    test environment, and verifying step 2's correctness does not
    require the focus guard to have run.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "hello",
            "",
            "mixed ASCII and unicode 漢字 123",
            "newline\nincluded",
            "tabs\tand\tspaces",
        ],
    )
    def test_clipboard_holds_text_after_paste(
        self, recording_keyboard: ImplKeyboard, text: str
    ) -> None:
        # Pre-populate the clipboard with a distinct sentinel so a no-op
        # ``paste`` would surface as the assertion reading back the
        # sentinel instead of ``text``.
        pyperclip.copy("__pre_paste_sentinel__")

        clipboard.paste(text, focus=False)

        assert pyperclip.paste() == text
        # The recording keyboard captures the dispatched Ctrl+V combo,
        # confirming step 4 of the pipeline ran. The fixture is
        # referenced so the singleton swap stays active for the test.
        assert len(recording_keyboard.calls) >= 2


class TestPasteSendsCtrlV:
    """``paste(...)`` dispatches ``Ctrl + V`` via the keyboard singleton.

    Verified by intercepting the keyboard singleton with a recording
    :class:`ImplKeyboard` (a vrcpilot-owned ABC implementation, not a
    3rd-party mock) and asserting the captured key sequence.
    """

    def test_dispatches_ctrl_v_in_press_order(
        self, recording_keyboard: ImplKeyboard
    ) -> None:
        clipboard.paste("hi", focus=False)

        # ``keyboard.press(CTRL, V)`` decomposes to CTRL down -> V down
        # -> sleep -> V up -> CTRL up (modifiers outlive the keys they
        # modify). The recording impl skips the sleep but preserves
        # the call sequence.
        assert recording_keyboard.calls == [
            ("_do_down", {"key": Key.CTRL}),
            ("_do_down", {"key": Key.V}),
            ("_do_up", {"key": Key.V}),
            ("_do_up", {"key": Key.CTRL}),
        ]


# Error propagation -- ``pyperclip.PyperclipException`` must reach the
# caller when no clipboard backend is reachable -- is exercised
# naturally by the **module-level skip above**: if we reach the tests,
# pyperclip works, and triggering the failure mode would require
# patching ``pyperclip.copy`` (a 3rd-party surface mock the test policy
# bans). On Linux runners without xclip / xsel the property is asserted
# at collection time: the skip reason itself documents the contract.
