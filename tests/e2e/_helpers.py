"""Shared utilities for the end-to-end VRChat test scenarios.

Each script in ``tests/e2e/`` follows the same pattern: ensure no
VRChat is running, drive the API or CLI, verify, and always clean up.
The helpers here keep that boilerplate in one place so individual
scenarios stay readable.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

# E2E scenarios run as scripts (``python tests/e2e/foo.py``) rather
# than via pytest, so the repo root is not on ``sys.path`` -- ``uv run``
# only injects ``src``. Bootstrap it here so ``from tests.helpers`` below
# resolves without each scenario having to repeat the dance.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import mss  # noqa: E402
import mss.tools  # noqa: E402
from PIL import Image  # noqa: E402

import vrcpilot  # noqa: E402
from tests.helpers import wait_for_no_pid, wait_for_pid  # noqa: E402

__all__ = [
    "ARTIFACT_DIR",
    "WARMUP_SECONDS",
    "ensure_no_vrchat",
    "log",
    "run_scenario",
    "save_image",
    "save_monitor_screenshot",
    "scenario_dir",
    "wait_for_no_pid",
    "wait_for_pid",
    "warmup",
]

# Fixed wait after a PID first appears, to let VRChat finish
# initializing -- not just spawning the process but also loading the
# default world and settling into a stable foreground state. 15s was
# enough for focus/unfocus probes that only need the window to exist,
# but synthetic input scenarios race the world load otherwise; 45s
# leaves headroom even on first-run shader compilation.
WARMUP_SECONDS: float = 30

#: Directory used by e2e scenarios to drop visual artifacts (PNGs).
#:
#: Located at ``<repo>/_e2e_artifacts/`` and gitignored. The preferred
#: way to write artifacts is via :func:`scenario_dir` (or the
#: :func:`save_monitor_screenshot` / :func:`save_image` wrappers that
#: build on it), which nests outputs as
#: ``_e2e_artifacts/<scenario>/<YYYYMMDD_HHMMSS>/<file>``. The constant
#: is retained for back-compat and for the rare case where a scenario
#: needs to compute paths outside the scenario/datetime layout. The
#: directory is created lazily by the helpers themselves, so callers do
#: not need to ensure existence first.
ARTIFACT_DIR: Path = Path(__file__).resolve().parents[2] / "_e2e_artifacts"

#: Process-scoped cache mapping scenario name -> resolved output dir.
#:
#: Populated lazily by :func:`scenario_dir`. The cache lives for the
#: lifetime of the Python process, so repeated calls from within a
#: single scenario reuse the same timestamp. ``tests/e2e/all.py``
#: launches each scenario in its own subprocess, which means each
#: scenario invocation starts with an empty cache and therefore gets a
#: fresh timestamped directory.
_SCENARIO_DIRS: dict[str, Path] = {}


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def scenario_dir(scenario: str) -> Path:
    """Return the per-run output directory for *scenario*, creating it once.

    On the first call for a given *scenario* name in this Python
    process, capture the current wall-clock as ``YYYYMMDD_HHMMSS``,
    build ``ARTIFACT_DIR / scenario / <stamp>``, ``mkdir`` it with
    ``parents=True, exist_ok=True``, and cache the result. Subsequent
    calls for the same *scenario* name return the cached path unchanged
    so every artifact written by one scenario run lands in the same
    timestamped directory. Different *scenario* names get independent
    timestamps.

    ``tests/e2e/all.py`` runs each scenario in its own subprocess, so a
    fresh Python process means a fresh cache, which means each scenario
    invocation gets its own ``<YYYYMMDD_HHMMSS>`` directory
    automatically — no per-run reset is required.

    Callers do not need to ``mkdir`` the returned path themselves; the
    helper does it on first use.

    Args:
        scenario: Scenario identifier used as the first path segment
            (e.g. ``"capture"``, ``"focus_unfocus"``).

    Returns:
        Absolute :class:`~pathlib.Path` to the per-run output directory.
    """
    cached = _SCENARIO_DIRS.get(scenario)
    if cached is not None:
        return cached
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ARTIFACT_DIR / scenario / stamp
    out.mkdir(parents=True, exist_ok=True)
    _SCENARIO_DIRS[scenario] = out
    return out


def ensure_no_vrchat() -> None:
    """Terminate any running VRChat and wait for it to disappear.

    Used as both pre- and post-condition by every scenario so a stray
    process from a prior failed run cannot pollute the test, and so the
    user's environment is left clean even on failure.
    """
    pids = vrcpilot.find_pids()
    if not pids:
        log("no existing VRChat process")
        return
    log(f"existing VRChat detected (pids={pids}); terminating")
    vrcpilot.terminate()
    if wait_for_no_pid():
        log("existing VRChat terminated")
    else:
        log("WARNING: VRChat still present after terminate()")


def warmup(seconds: float = WARMUP_SECONDS) -> None:
    """Sleep *seconds* to let VRChat settle after launch."""
    log(f"warming up for {seconds:.0f}s")
    time.sleep(seconds)


def save_monitor_screenshot(scenario: str, label: str) -> Path:
    """Capture all monitors and save under ``_e2e_artifacts/``.

    For a VRChat-window-only screenshot, use :func:`vrcpilot.take_screenshot`
    instead; this helper is for whole-desktop visual records.

    Use this in e2e scenarios to leave a visual record at key steps
    so a human can review what VRChat looked like after the action ran.
    The save location is also emitted via :func:`log`.

    Args:
        scenario: Scenario identifier used as the per-scenario
            directory name (e.g. ``"focus_unfocus"``).
        label: Step name within the scenario (e.g. ``"focus"``,
            ``"unfocus"``); becomes the file name.

    Returns:
        Absolute :class:`~pathlib.Path` to the saved PNG. The output
        path is ``_e2e_artifacts/<scenario>/<YYYYMMDD_HHMMSS>/{label}.png``;
        the timestamp segment is shared by every artifact written by
        the same scenario run (see :func:`scenario_dir`).
    """
    path = scenario_dir(scenario) / f"{label}.png"
    with mss.mss() as sct:
        img = sct.grab(sct.monitors[0])
    mss.tools.to_png(img.rgb, img.size, output=str(path))
    log(f"screenshot saved: {path}")
    return path


def save_image(scenario: str, label: str, image: Image.Image) -> Path:
    """Save a :class:`PIL.Image.Image` under :data:`ARTIFACT_DIR`.

    Companion to :func:`save_monitor_screenshot`: the latter grabs the
    whole desktop with mss, while this one persists an image the
    scenario already has in hand (e.g. a ``vrcpilot.Capture`` frame
    converted via ``Image.fromarray``, or a
    ``vrcpilot.take_screenshot()`` result). Both share the same
    ``scenario/<YYYYMMDD_HHMMSS>/`` layout so artifacts from a single
    scenario run group together under one timestamped directory.

    Args:
        scenario: Scenario identifier used as the per-scenario
            directory name (e.g. ``"capture"``).
        label: Step name within the scenario
            (e.g. ``"first"``, ``"last"``); becomes the file name.
        image: Image to save. Format is inferred from the ``.png``
            suffix.

    Returns:
        Absolute :class:`~pathlib.Path` to the saved PNG. The output
        path is ``_e2e_artifacts/<scenario>/<YYYYMMDD_HHMMSS>/{label}.png``;
        the timestamp segment is shared by every artifact written by
        the same scenario run (see :func:`scenario_dir`).
    """
    out = scenario_dir(scenario) / f"{label}.png"
    image.save(out)
    return out


def run_scenario(name: str, body: Callable[[], None]) -> int:
    """Run *body* with pre/post cleanup and convert the outcome to an exit
    code.

    *body* may return normally for success, or raise to signal failure.
    Either way :func:`ensure_no_vrchat` runs both before and after, and a
    final ``PASS:`` / ``FAIL:`` line is emitted.
    """
    # Lift the root logger to INFO so library diagnostics (e.g. the
    # PipeWire speaker backend's per-sink_input scan lines) reach the
    # scenario's stderr. ``force=True`` overrides any prior
    # ``basicConfig`` so a re-run within the same process still picks
    # up the format change. pytest's ``log_cli`` does not apply here:
    # e2e scenarios run as scripts, not under pytest.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        force=True,
    )
    log(f"=== scenario: {name} ===")
    log("pre-cleanup")
    ensure_no_vrchat()
    try:
        body()
    except Exception as exc:
        log(f"scenario raised: {exc!r}")
        print(f"FAIL: {name}: {exc}", flush=True)
        return 1
    finally:
        log("post-cleanup")
        ensure_no_vrchat()
    print(f"PASS: {name}", flush=True)
    return 0
