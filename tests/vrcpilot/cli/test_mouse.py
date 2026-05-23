"""Tests for :mod:`vrcpilot.cli.mouse`.

The CLI calls into :mod:`vrcpilot.controls.mouse` via the ``mouse_api``
re-export. Patching :func:`vrcpilot.controls.mouse._get` to return an
:class:`~tests.helpers.ImplMouse` lets the real public ``mouse.move``
/ ``mouse.click`` / ``mouse.scroll`` functions run end-to-end (focus
guard included) while keeping the backend out of the test. The guard
itself is stubbed to a no-op so tests do not need a live VRChat
process; the guard-failure tests deliberately re-arm the stub to raise.

``press`` / ``release`` are intentionally NOT exposed by the CLI:
each invocation opens and closes its own backend, so a held button
auto-releases as the process exits. The test class
:class:`TestMouseRemovedActions` locks that contract in.
"""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from tests.helpers import ImplMouse
from vrcpilot.cli import main
from vrcpilot.controls import VRChatNotFocusedError
from vrcpilot.controls.mouse import MouseButton
from vrcpilot.process import VRChatMultipleInstancesError, VRChatNotRunningError


@pytest.fixture
def fake_mouse(mocker: MockerFixture) -> ImplMouse:
    """Wire the public ``mouse`` module to a recording :class:`ImplMouse`.

    Also stubs :func:`vrcpilot.controls.guard.ensure_target` to a no-op
    and pins :func:`vrcpilot.geometry.get_vrchat_window_rect` to an
    origin-anchored rectangle so the window-local -> desktop translation
    in :meth:`Mouse.move` is a no-op and existing CLI tests can keep
    asserting on raw coordinates.
    """
    impl = ImplMouse()
    mocker.patch("vrcpilot.controls.mouse._get", return_value=impl)
    mocker.patch("vrcpilot.controls.mouse.base.ensure_target", return_value=None)
    mocker.patch(
        "vrcpilot.controls.mouse.base.get_vrchat_window_rect",
        return_value=(0, 0, 1920, 1080),
    )
    return impl


class TestMouseMove:
    @pytest.mark.parametrize(
        ("argv", "expected_relative"),
        [
            (["mouse", "move", "100", "200"], False),
            (["mouse", "move", "100", "200", "--rel"], True),
            (["mouse", "move", "-50", "75", "--rel"], True),
        ],
    )
    def test_dispatches_with_correct_relative_flag(
        self,
        fake_mouse: ImplMouse,
        argv: list[str],
        expected_relative: bool,
    ):
        exit_code = main(argv)

        assert exit_code == 0
        assert len(fake_mouse.calls) == 1
        name, kwargs = fake_mouse.calls[0]
        assert name == "_do_move"
        assert kwargs["x"] == int(argv[2])
        assert kwargs["y"] == int(argv[3])
        assert kwargs["relative"] is expected_relative

    def test_silent_on_success(
        self, fake_mouse: ImplMouse, capsys: pytest.CaptureFixture[str]
    ):
        del fake_mouse  # fixture activates the patches
        exit_code = main(["mouse", "move", "0", "0"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestMouseClick:
    def test_default_button_is_left(self, fake_mouse: ImplMouse):
        exit_code = main(["mouse", "click"])

        assert exit_code == 0
        assert fake_mouse.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]

    @pytest.mark.parametrize(
        ("button_arg", "expected_button"),
        [
            ("left", MouseButton.LEFT),
            ("right", MouseButton.RIGHT),
            ("middle", MouseButton.MIDDLE),
        ],
    )
    def test_button_override(
        self,
        fake_mouse: ImplMouse,
        button_arg: str,
        expected_button: MouseButton,
    ):
        exit_code = main(["mouse", "click", button_arg])

        assert exit_code == 0
        assert fake_mouse.calls == [
            ("_do_press", {"button": expected_button}),
            ("_do_release", {"button": expected_button}),
        ]

    def test_count_and_duration_propagation(
        self, fake_mouse: ImplMouse, mocker: MockerFixture
    ):
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")

        exit_code = main(
            ["mouse", "click", "right", "--count", "3", "--duration", "0.05"]
        )

        assert exit_code == 0
        # count=3 cycles of press / release for the same button.
        assert (
            fake_mouse.calls
            == [
                ("_do_press", {"button": MouseButton.RIGHT}),
                ("_do_release", {"button": MouseButton.RIGHT}),
            ]
            * 3
        )
        assert sleep_spy.call_count == 3
        for call in sleep_spy.call_args_list:
            assert call.args == (0.05,)

    def test_argparse_rejects_unknown_button(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["mouse", "click", "foobar"])

        assert excinfo.value.code != 0
        # argparse writes its error to stderr; just ensure something landed.
        captured = capsys.readouterr()
        assert captured.err != ""

    def test_click_two_buttons_simultaneously(self, fake_mouse: ImplMouse):
        exit_code = main(["mouse", "click", "left", "right"])

        assert exit_code == 0
        assert fake_mouse.calls == [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]

    def test_click_three_buttons_with_count_and_duration(
        self, fake_mouse: ImplMouse, mocker: MockerFixture
    ):
        sleep_spy = mocker.patch("vrcpilot.controls.mouse.base.time.sleep")

        exit_code = main(
            [
                "mouse",
                "click",
                "left",
                "right",
                "middle",
                "--count",
                "2",
                "--duration",
                "0.05",
            ]
        )

        assert exit_code == 0
        cycle = [
            ("_do_press", {"button": MouseButton.LEFT}),
            ("_do_press", {"button": MouseButton.RIGHT}),
            ("_do_press", {"button": MouseButton.MIDDLE}),
            ("_do_release", {"button": MouseButton.MIDDLE}),
            ("_do_release", {"button": MouseButton.RIGHT}),
            ("_do_release", {"button": MouseButton.LEFT}),
        ]
        assert fake_mouse.calls == cycle * 2
        assert sleep_spy.call_count == 2
        for call in sleep_spy.call_args_list:
            assert call.args == (0.05,)


class TestMouseScroll:
    @pytest.mark.parametrize("amount", [3, -3, 0])
    def test_scroll_amount(self, fake_mouse: ImplMouse, amount: int):
        exit_code = main(["mouse", "scroll", str(amount)])

        assert exit_code == 0
        assert fake_mouse.calls == [("_do_scroll", {"amount": amount})]


class TestMouseRemovedActions:
    @pytest.mark.parametrize("removed", ["press", "release"])
    def test_press_and_release_are_not_exposed(
        self, removed: str, capsys: pytest.CaptureFixture[str]
    ):
        # The CLI deliberately drops press / release: each invocation
        # opens and closes its own backend, so a held button would
        # auto-release as the process exits.
        with pytest.raises(SystemExit) as excinfo:
            main(["mouse", removed])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""


class TestMouseGuardErrors:
    def test_not_running_error_returns_exit_1(
        self,
        fake_mouse: ImplMouse,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_mouse  # fixture wires the impl, but the guard fires first
        mocker.patch(
            "vrcpilot.controls.mouse.base.ensure_target",
            side_effect=VRChatNotRunningError("VRChat is not running"),
        )

        exit_code = main(["mouse", "click"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err
        assert "VRChat is not running" in captured.err

    def test_not_focused_error_returns_exit_1(
        self,
        fake_mouse: ImplMouse,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_mouse
        mocker.patch(
            "vrcpilot.controls.mouse.base.ensure_target",
            side_effect=VRChatNotFocusedError("VRChat is not focused"),
        )

        exit_code = main(["mouse", "move", "0", "0"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err
        assert "VRChat is not focused" in captured.err


class TestMouseDispatch:
    def test_no_action_exits_non_zero(self, capsys: pytest.CaptureFixture[str]):
        # ``add_subparsers(required=True)`` makes argparse error out
        # when ``vrcpilot mouse`` is invoked without a sub-action.
        with pytest.raises(SystemExit) as excinfo:
            main(["mouse"])

        assert excinfo.value.code != 0
        captured = capsys.readouterr()
        assert captured.err != ""


class TestMousePidArg:
    """``--pid`` is wired on every mouse action sub-subcommand."""

    def test_move_passes_pid_to_api(self, fake_mouse: ImplMouse, mocker: MockerFixture):
        del fake_mouse
        spy = mocker.patch("vrcpilot.cli.mouse.mouse_api.move")

        exit_code = main(["mouse", "move", "10", "20", "--pid", "555"])

        assert exit_code == 0
        spy.assert_called_once_with(10, 20, relative=False, pid=555)

    def test_click_passes_pid_to_api(
        self, fake_mouse: ImplMouse, mocker: MockerFixture
    ):
        del fake_mouse
        spy = mocker.patch("vrcpilot.cli.mouse.mouse_api.click")

        exit_code = main(["mouse", "click", "right", "--pid", "777"])

        assert exit_code == 0
        spy.assert_called_once_with(MouseButton.RIGHT, count=1, duration=0.0, pid=777)

    def test_scroll_passes_pid_to_api(
        self, fake_mouse: ImplMouse, mocker: MockerFixture
    ):
        del fake_mouse
        spy = mocker.patch("vrcpilot.cli.mouse.mouse_api.scroll")

        exit_code = main(["mouse", "scroll", "3", "--pid", "999"])

        assert exit_code == 0
        spy.assert_called_once_with(3, pid=999)

    def test_no_pid_passes_none(self, fake_mouse: ImplMouse, mocker: MockerFixture):
        del fake_mouse
        spy = mocker.patch("vrcpilot.cli.mouse.mouse_api.move")

        exit_code = main(["mouse", "move", "10", "20"])

        assert exit_code == 0
        spy.assert_called_once_with(10, 20, relative=False, pid=None)

    def test_multiple_instances_exits_with_diagnostic(
        self,
        fake_mouse: ImplMouse,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ):
        del fake_mouse
        # ``VRChatMultipleInstancesError`` is a subclass of
        # ``VRChatNotRunningError`` -- the CLI must catch it first or
        # the multi-instance branch never runs.
        mocker.patch(
            "vrcpilot.controls.mouse.base.ensure_target",
            side_effect=VRChatMultipleInstancesError([100, 200]),
        )

        exit_code = main(["mouse", "click"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert (
            captured.err == "vrcpilot: multiple VRChat instances detected "
            "(PIDs: 100 200); pass --pid\n"
        )
