"""Linux-only helpers for :mod:`vrcpilot.process`."""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError("vrcpilot.process.linux is Linux-only")

import os
import shutil
from pathlib import Path

from .errors import (
    UmuLauncherNotFoundError,
    VRChatDisplayNotAvailableError,
    VRChatSteamCompatdataNotFoundError,
)


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


def steam_compatdata_pfx(launcher: Path, app_id: int) -> Path:
    """Return the Steam-managed Proton prefix for VRChat as a path.

    Assumes ``launcher`` is ``<library>/steamapps/common/VRChat/launch.exe``
    (the standard layout :func:`vrcpilot.process.executable.find_vrchat_launcher`
    returns). The Steam library root is recovered by stripping the three
    intermediate directories (``steamapps/common/VRChat``) plus the
    filename, and the prefix lives at
    ``<library>/steamapps/compatdata/<app_id>/pfx``.

    Path-only: existence is the caller's concern (the launch flow raises
    :class:`VRChatSteamCompatdataNotFoundError` when missing).
    """
    # parents[3] strips launch.exe + VRChat + common + steamapps, leaving
    # the library root. Equivalent to .parent.parent.parent.parent but
    # the indexed form makes the "how many levels" claim self-checking.
    library = launcher.parents[3]
    return library / "steamapps" / "compatdata" / str(app_id) / "pfx"


def profile_wineprefix(profile: int) -> Path:
    """Return the vrcpilot-managed ``$WINEPREFIX`` path for a profile slot.

    Path-only: directory creation is the caller's responsibility (the
    launch flow does ``mkdir(parents=True, exist_ok=True)`` right before
    spawning).
    """
    base = Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share").expanduser()
    return base / "vrcpilot" / "profiles" / str(profile) / "wineprefix"


def resolve_direct_spawn_wineprefix(
    *,
    launcher: Path,
    app_id: int,
    wineprefix: Path | None,
    profile: int | None,
) -> Path | None:
    """Pick the ``$WINEPREFIX`` to export for a Linux direct-spawn run.

    Encodes the priority order shared by :func:`vrcpilot.process.launch`:

    1. Explicit ``wineprefix`` override wins unconditionally.
    2. ``profile == 0`` reuses Steam's own ``compatdata/<app_id>/pfx``
       so login state and SaveData line up with a ``--via-steam`` run.
       Raises :class:`VRChatSteamCompatdataNotFoundError` (no silent
       fallback to a fresh prefix) when that path does not exist yet.
    3. ``profile >= 1`` maps to a vrcpilot-managed per-profile prefix
       under :func:`profile_wineprefix`, creating the directory on
       demand so umu-run can populate it.
    4. ``profile is None`` (no prefix flag, no profile flag) returns
       ``None`` -- the caller leaves ``$WINEPREFIX`` unset and umu-run
       falls back to its default location.

    Raises:
        VRChatSteamCompatdataNotFoundError: ``profile == 0`` but the
            Steam-managed prefix has not been initialised. The message
            tells the user how to bootstrap it (run ``--via-steam``
            once) or override (``--wineprefix=<path>``).
    """
    if wineprefix is not None:
        return wineprefix
    if profile == 0:
        steam_pfx = steam_compatdata_pfx(launcher, app_id)
        if not steam_pfx.is_dir():
            raise VRChatSteamCompatdataNotFoundError(
                "Steam-managed wineprefix for VRChat is missing: "
                f"{steam_pfx}. Run `vrcpilot launch --via-steam` "
                "once to initialise it, or pass --wineprefix=<path> "
                "to override."
            )
        return steam_pfx
    if profile is not None:
        generated = profile_wineprefix(profile)
        generated.mkdir(parents=True, exist_ok=True)
        return generated
    return None


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
