"""E2E scenario: drive ``vrcpilot.keyboard`` against real VRChat.

Launches VRChat in Desktop mode, warms up, then exercises the
keyboard module across two angles a human can verify by eye:

* **ESC toggles VRChat's LaunchPad** (Quick Menu in Desktop mode).
  After launch the menu is hidden, so a single ``Key.ESCAPE`` press
  shows it; another press hides it again. Repeating the pair across
  4 alternating steps proves the call is idempotent (same as the
  ``focus_unfocus`` pattern), and each step's screenshot lands at
  ``_e2e_artifacts/keyboard/<YYYYMMDD_HHMMSS>/<step>.png`` for review.
* **A modifier combo** is sandwiched between the toggle steps in two
  forms back-to-back: the explicit ``down(SHIFT_LEFT)`` ->
  ``press(A)`` -> ``up(SHIFT_LEFT)`` triple, and the one-shot variadic
  ``press(SHIFT_LEFT, A)`` that drives the same down / sleep / up
  cycle from a single call. Whether or not VRChat has a focused text
  field at that moment, both calls must complete without raising and
  the subsequent ESC toggles must keep working -- a stuck SHIFT
  modifier would visibly break later steps.

Run with::

    just e2e-test keyboard

Prerequisites:

* Desktop session must be reachable (X11 or XWayland on Linux; native
  Wayland is rejected by ``ensure_target``). On Windows, no display
  setup is needed beyond a logged-in interactive session.
* Steam must already be running -- ``vrcpilot.launch()`` will time out
  otherwise.
* On Linux, the current user needs write access to ``/dev/uinput`` for
  inputtino to open its virtual device. If construction fails with a
  ``RuntimeError``, run::

      sudo usermod -aG input $USER

  and log out / back in (or follow your distro's udev rule guidance).
* On Windows, no extra setup is required: ``pydirectinput`` drives
  ``SendInput`` directly.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import vrcpilot
from vrcpilot import Key, keyboard

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402


def _scenario() -> None:
    _helpers.log("calling vrcpilot.launch(no_vr=True)")
    vrcpilot.launch(no_vr=True)

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    # 4-step idempotence pattern: ESC toggles the LaunchPad / Quick
    # Menu. After launch the menu is hidden, so the first ESC opens
    # it, the second closes it, and repeating the pair proves the
    # call is idempotent.

    # Step 1/4: open LaunchPad.
    _helpers.log("keyboard.press(Key.ESCAPE) (1/4: open LaunchPad)")
    keyboard.press(Key.ESCAPE)
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("keyboard", "1_open")

    # Step 2/4: close LaunchPad.
    _helpers.log("keyboard.press(Key.ESCAPE) (2/4: close LaunchPad)")
    keyboard.press(Key.ESCAPE)
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("keyboard", "2_close")

    # Mid-scenario: modifier combo, both forms. The explicit triple
    # (down -> press -> up) and the one-shot variadic press should be
    # observably equivalent. The call must complete without raising
    # and SHIFT must not stick -- a stuck modifier would visibly
    # break the ESC toggles in later steps.
    _helpers.log(
        "keyboard.down(SHIFT_LEFT) -> press(A) -> up(SHIFT_LEFT) (modifier combo, explicit)"
    )
    keyboard.down(Key.SHIFT_LEFT)
    time.sleep(0.05)
    keyboard.press(Key.A)
    time.sleep(0.05)
    keyboard.up(Key.SHIFT_LEFT)
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("keyboard", "3a_combo_explicit")

    _helpers.log("keyboard.press(SHIFT_LEFT, A) (modifier combo, one-shot variadic)")
    keyboard.press(Key.SHIFT_LEFT, Key.A)
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("keyboard", "3b_combo_oneshot")

    # Step 3/4: open LaunchPad again to verify idempotence and that
    # the modifier was released cleanly.
    _helpers.log("keyboard.press(Key.ESCAPE) (3/4: open LaunchPad again)")
    keyboard.press(Key.ESCAPE)
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("keyboard", "4_open_again")

    # Step 4/4: close LaunchPad. Final state matches the natural
    # post-launch state (menu hidden), so VRChat is left tidy for
    # post-cleanup.
    _helpers.log("keyboard.press(Key.ESCAPE) (4/4: close LaunchPad)")
    keyboard.press(Key.ESCAPE)
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("keyboard", "5_close_again")


def main() -> int:
    return _helpers.run_scenario("keyboard", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
