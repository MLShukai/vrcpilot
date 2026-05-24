"""Linux-only helpers for :mod:`vrcpilot.process`."""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError("vrcpilot.process.linux is Linux-only")

import os
import shutil
from pathlib import Path

from .errors import UmuLauncherNotFoundError, VRChatDisplayNotAvailableError


def find_umu_launcher(override: Path | None = None) -> Path:
    """Return the ``umu-run`` executable path.

    Resolution order:

    1. ``override`` argument.
    2. ``shutil.which('umu-run')`` against PATH.

    Raises:
        UmuLauncherNotFoundError: No ``umu-run`` found. The message links to
            the umu-launcher project so the user can install it.
    """
    if override is not None:
        if override.is_file():
            return override
        raise UmuLauncherNotFoundError(
            f"umu-run not found at override path: {override}"
        )

    located = shutil.which("umu-run")
    if located is None:
        raise UmuLauncherNotFoundError(
            "umu-run not found on PATH. Install umu-launcher (see README's "
            "Linux setup) or use vrcpilot launch --via-steam to delegate to "
            "Steam-managed Proton."
        )
    return Path(located)


def profile_wineprefix(profile: int) -> Path:
    """Return the vrcpilot-managed ``$WINEPREFIX`` path for a profile slot.

    Path-only: directory creation is the caller's responsibility (the
    launch flow does ``mkdir(parents=True, exist_ok=True)`` right before
    spawning).
    """
    base = Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share").expanduser()
    return base / "vrcpilot" / "profiles" / str(profile) / "wineprefix"


def preflight_linux_environment(*, via_steam: bool) -> None:
    """Fail fast on Linux launch preconditions that would otherwise hang.

    Two different gates depending on the spawn route:

    * **Direct-spawn** (``via_steam=False``): the ``umu-run`` + Wine
      subprocess blocks indefinitely when no graphical session is
      attached (a real failure mode under plain SSH). We pre-check
      ``$DISPLAY`` / ``$WAYLAND_DISPLAY`` and raise
      :class:`VRChatDisplayNotAvailableError` so the caller sees an
      immediate, actionable error instead of a hung process. Either
      X11 or Wayland is enough.
    * **Via-Steam** (``via_steam=True``): ``steam.exe -applaunch``
      assumes Steam is already running (Steam owns its own display
      attachment). vrcpilot cannot start the Steam UI for the user, so
      a missing Steam process is surfaced via
      :class:`SteamNotRunningError`.

    Raises:
        VRChatDisplayNotAvailableError: Direct-spawn route with neither
            ``$DISPLAY`` nor ``$WAYLAND_DISPLAY`` set. Empty strings count
            as unset (stripped systemd unit envs frequently produce this).
        SteamNotRunningError: Via-Steam route but no Steam client is
            running on the host.
    """
    if via_steam:
        from vrcpilot.steam import SteamNotRunningError, is_steam_running

        if not is_steam_running():
            raise SteamNotRunningError(
                "Steam client is not running on this Linux host. "
                "Start the Steam desktop client in a graphical session "
                "before retrying launch(via_steam=True)."
            )
        return
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise VRChatDisplayNotAvailableError(
            "Neither DISPLAY nor WAYLAND_DISPLAY is set; "
            "vrcpilot launch (direct-spawn) requires a graphical session. "
            "Run from a desktop session, or set DISPLAY=:0 (or WAYLAND_DISPLAY) "
            "before invoking launch()."
        )
