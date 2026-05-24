"""E2E scenario: drive VRChat through the ``vrcpilot`` CLI.

Runs ``vrcpilot launch`` / ``pid`` / ``terminate`` via ``uv run`` and
verifies each subcommand's exit code and stdout. ``_helpers.run_scenario``
ensures VRChat is killed before and after the run regardless of outcome.

The CLI exposes machine-readable output (PIDs on their own lines, exit
code 0 = running / 1 = absent), so this scenario validates the contract
that shell pipelines depend on (e.g. ``pid=$(vrcpilot launch)``).

Run with::

    just e2e-test cli_launch_terminate
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _helpers  # noqa: E402


def _vrcpilot(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``uv run vrcpilot <args>`` and return the completed process."""
    cmd = ["uv", "run", "vrcpilot", *args]
    _helpers.log(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.stdout:
        _helpers.log(f"  stdout: {result.stdout.strip()}")
    if result.stderr:
        _helpers.log(f"  stderr: {result.stderr.strip()}")
    _helpers.log(f"  exit: {result.returncode}")
    return result


def _scenario() -> None:
    initial_pid = _vrcpilot("pid")
    assert (
        initial_pid.returncode == 1
    ), f"initial pid exit code: expected 1, got {initial_pid.returncode}"
    assert (
        initial_pid.stdout == ""
    ), f"initial pid stdout should be empty, got {initial_pid.stdout!r}"

    launch = _vrcpilot("launch")
    assert (
        launch.returncode == 0
    ), f"launch exit code: expected 0, got {launch.returncode}"
    launch_stdout = launch.stdout.strip()
    assert (
        launch_stdout.isdigit()
    ), f"launch stdout should be a single PID, got {launch.stdout!r}"
    launched_pid = int(launch_stdout)
    _helpers.log(f"launch reported PID = {launched_pid}")

    _helpers.warmup()

    running = _vrcpilot("pid")
    assert (
        running.returncode == 0
    ), f"running pid exit code: expected 0, got {running.returncode}"
    running_pids = [int(line) for line in running.stdout.strip().splitlines()]
    assert (
        launched_pid in running_pids
    ), f"launch PID {launched_pid} not in running pids {running_pids}"

    terminate = _vrcpilot("terminate")
    assert (
        terminate.returncode == 0
    ), f"terminate exit code: expected 0, got {terminate.returncode}"
    killed_pids = [int(line) for line in terminate.stdout.strip().splitlines()]
    assert (
        launched_pid in killed_pids
    ), f"launch PID {launched_pid} not in killed pids {killed_pids}"

    final = _vrcpilot("pid")
    assert (
        final.returncode == 1
    ), f"final pid exit code: expected 1, got {final.returncode}"


def main() -> int:
    return _helpers.run_scenario("cli_launch_terminate", _scenario)


if __name__ == "__main__":
    raise SystemExit(main())
