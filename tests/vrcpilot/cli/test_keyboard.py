"""Tests for :mod:`vrcpilot.cli.keyboard`.

``vrcpilot keyboard press`` dispatches to
:func:`vrcpilot.controls.keyboard.press` after the same focus guard
shared by ``mouse``. Argv parsing turns string keys into
:class:`vrcpilot.controls.keyboard.Key` enum members; an unknown name
exits 2 via argparse.

The success path (synthetic keypress reaching VRChat) requires
``inputtino`` / ``pydirectinput`` plus a live VRChat -- deferred to
the e2e suite. Argparse-only assertions through
:func:`vrcpilot.cli.build_parser` run on every platform.
"""

from __future__ import annotations

import sys

import pytest

from tests.helpers import has_uinput
from vrcpilot.cli import build_parser, main
from vrcpilot.controls.keyboard import Key

#: Skip the focus-guard tests when the platform backend cannot be
#: instantiated. On Linux ``LinuxKeyboard.__init__`` calls
#: ``inputtino.Keyboard()`` which fails with ``RuntimeError: Permission
#: denied`` when ``/dev/uinput`` is not writable (typical for default
#: CI runners). On Windows ``Win32Keyboard`` has no equivalent eager
#: dependency so the marker is a no-op there.
_requires_real_backend = pytest.mark.skipif(
    sys.platform == "linux" and not has_uinput(),
    reason="LinuxKeyboard needs /dev/uinput write access (inputtino)",
)


class TestKeyboardArgparse:
    """Sub-subcommand-level argparse plumbing."""

    def test_press_parses_single_key(self):
        ns = build_parser().parse_args(["keyboard", "press", "a"])
        assert ns.keyboard_action == "press"
        assert ns.keys == [Key.A]

    def test_press_parses_multiple_keys(self):
        ns = build_parser().parse_args(["keyboard", "press", "ctrl", "a"])
        assert ns.keys == [Key.CTRL, Key.A]

    def test_press_default_duration_is_one_tenth_second(self):
        # 0.1s is the documented lower bound for VRChat / Unity to
        # register a keypress reliably -- never regress to 0.0.
        ns = build_parser().parse_args(["keyboard", "press", "a"])
        assert ns.duration == pytest.approx(0.1)

    def test_press_custom_duration(self):
        ns = build_parser().parse_args(["keyboard", "press", "a", "--duration", "0.3"])
        assert ns.duration == pytest.approx(0.3)

    def test_press_requires_at_least_one_key(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["keyboard", "press"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_press_rejects_unknown_key_name(self, capsys: pytest.CaptureFixture[str]):
        # ``type=Key`` triggers a ValueError on bad enum names, which
        # argparse surfaces as exit 2.
        with pytest.raises(SystemExit) as excinfo:
            main(["keyboard", "press", "not-a-key"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_action_required(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["keyboard"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""


@_requires_real_backend
class TestKeyboardNoVRChat:
    """The focus guard fires when no VRChat is running."""

    def test_press_exits_1(
        self,
        not_wayland_native: None,
        capsys: pytest.CaptureFixture[str],
    ):
        del not_wayland_native
        assert main(["keyboard", "press", "a", "--duration", "0.0"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err
