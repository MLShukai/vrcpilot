"""VRChat ``launch.exe`` / Steam library 探索 helper。"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from .errors import VRChatLauncherNotFoundError

#: launch.exe の Steam 配下相対パス。
_LAUNCHER_RELATIVE: Path = Path("steamapps/common/VRChat/launch.exe")

#: $VRCHAT_LAUNCHER 環境変数名。
_LAUNCHER_ENV_VAR: str = "VRCHAT_LAUNCHER"


def parse_steam_library_paths(vdf_path: Path) -> list[Path]:
    """Extract path entries from a Steam ``libraryfolders.vdf``."""
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', text)]


def windows_steam_paths() -> list[Path]:
    """Return candidate Steam install **roots** on Windows.

    Responsibility is limited to enumerating Steam install roots from
    ``HKCU\\Software\\Valve\\Steam\\SteamPath`` plus the standard installer
    paths. Expanding each root's ``steamapps/libraryfolders.vdf`` into the
    real list of Steam libraries is the caller's job
    (:func:`find_vrchat_launcher`), so there is exactly one place that
    knows how Steam library discovery works.
    """
    candidates: list[Path] = []
    # ``sys.platform == "win32"`` narrows so pyright resolves the Windows-only
    # ``winreg`` stubs from typeshed; without the guard the import is unknown
    # on POSIX type-check runs.
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"
            ) as key:
                value, _ = winreg.QueryValueEx(key, "SteamPath")
            if isinstance(value, str):
                candidates.append(Path(value))
        except (ImportError, OSError, FileNotFoundError):
            pass

    candidates.extend(
        [
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
        ]
    )
    return candidates


def linux_steam_paths() -> list[Path]:
    """Return candidate Steam install **roots** on Linux.

    Mirrors :func:`windows_steam_paths`: only enumerate install roots and
    leave ``libraryfolders.vdf`` expansion to the caller.
    """
    return [
        Path("~/.steam/steam").expanduser(),
        Path("~/.local/share/Steam").expanduser(),
    ]


def find_vrchat_launcher(override: Path | None = None) -> Path:
    """Return the verified ``launch.exe`` path.

    Resolution order:

    1. ``override`` argument (CLI ``--vrchat-launcher``, API ``vrchat_launcher=``).
    2. ``$VRCHAT_LAUNCHER`` environment variable.
    3. Steam library discovery via ``libraryfolders.vdf`` + standard paths.

    Each candidate is validated with ``Path.is_file()`` before being returned.

    Raises:
        VRChatLauncherNotFoundError: No candidate resolves to an existing
            ``launch.exe`` file. The message includes the candidates tried so
            the user can pick the right ``--vrchat-launcher`` value.
    """
    if override is not None:
        if override.is_file():
            return override
        raise VRChatLauncherNotFoundError(
            f"VRChat launch.exe not found at override path: {override}"
        )

    tried: list[Path] = []

    env_value = os.environ.get(_LAUNCHER_ENV_VAR)
    if env_value:
        env_path = Path(env_value)
        tried.append(env_path)
        if env_path.is_file():
            return env_path

    if sys.platform == "win32":
        roots = windows_steam_paths()
    elif sys.platform == "linux":
        roots = linux_steam_paths()
    else:
        roots = []

    # Each ``root`` is a Steam install root; the libraries it owns live in
    # ``steamapps/libraryfolders.vdf``. Centralising the vdf expansion here
    # keeps Steam library discovery in one place. When the vdf is missing
    # (fresh install / non-standard layout) we treat the root itself as a
    # library so single-library setups still resolve.
    libraries: list[Path] = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        libraries.extend(parse_steam_library_paths(vdf) if vdf.is_file() else [root])

    for candidate in dict.fromkeys(lib / _LAUNCHER_RELATIVE for lib in libraries):
        tried.append(candidate)
        if candidate.is_file():
            return candidate

    raise VRChatLauncherNotFoundError(
        "VRChat launch.exe could not be located in any Steam library. "
        f"Tried: {[str(p) for p in tried]}. "
        "Pass --vrchat-launcher <path> or set $VRCHAT_LAUNCHER."
    )
