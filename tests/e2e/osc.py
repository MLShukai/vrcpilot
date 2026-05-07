"""E2E scenario: send OSC messages to a real VRChat client.

Drives :class:`vrcpilot.OscSender` against a launched VRChat to confirm
controller (chatbox / movement / jump) and avatar parameter writes do
not raise. The avatar parameter writes use synthetic parameter names so
the test does not depend on which avatar is currently loaded - VRChat
silently ignores parameters the active avatar does not declare while
the OSC send itself still succeeds.

Run with::

    just e2e-test osc
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import vrcpilot

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402

# Use a non-default port to avoid colliding with another OSC tool the
# user may already have bound to 9000.
_OSC_IN_PORT = 9100


def _scenario() -> None:
    _helpers.log(f"calling vrcpilot.launch(no_vr=True, osc=in_port={_OSC_IN_PORT})")
    vrcpilot.launch(no_vr=True, osc=vrcpilot.OscConfig(in_port=_OSC_IN_PORT))

    _helpers.log("waiting for VRChat PID")
    pid = _helpers.wait_for_pid()
    assert pid is not None, "VRChat PID was not observed before timeout"
    _helpers.log(f"VRChat started (pid={pid})")

    _helpers.warmup()

    sender = vrcpilot.OscSender(port=_OSC_IN_PORT)
    ctrl = sender.controller()
    avatars = sender.avatar_parameters()

    _helpers.save_monitor_screenshot("osc", "0_before")

    _helpers.log("chatbox: send a message")
    ctrl.chatbox("vrcpilot OSC e2e", send=True, sfx=False)
    time.sleep(1.0)
    _helpers.save_monitor_screenshot("osc", "1_chatbox")

    _helpers.log("movement: run + vertical(1.0) for 1s")
    ctrl.run(True)
    ctrl.vertical(1.0)
    time.sleep(1.0)
    ctrl.vertical(0.0)
    ctrl.run(False)
    _helpers.save_monitor_screenshot("osc", "2_after_move")

    _helpers.log("tap: jump()")
    ctrl.jump()
    time.sleep(0.5)
    _helpers.save_monitor_screenshot("osc", "3_after_jump")

    # Avatar parameter writes are a smoke test only. VRChat silently
    # ignores parameters the active avatar does not declare, so we use
    # synthetic names - the assertion is just "OSC send did not raise".
    _helpers.log("avatar parameters: smoke test (no avatar dependency)")
    avatars.send_bool("vrcpilot_test_bool", True)
    avatars.send_int("vrcpilot_test_int", 1)
    avatars.send_float("vrcpilot_test_float", 0.5)

    # Escape hatch: arbitrary message via sender.send (no validation).
    sender.send("/avatar/parameters/vrcpilot_test_raw", 42)

    _helpers.log("OSC e2e: all commands sent without exceptions")


def main() -> int:
    return _helpers.run_scenario("osc", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
