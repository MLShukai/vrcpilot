"""Steam executable discovery and runtime-state probing."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import psutil


class SteamNotFoundError(RuntimeError):
    """Raised when the Steam executable cannot be located."""


class SteamNotRunningError(RuntimeError):
    """Linux ``launch(via_steam=True)`` requires a Steam UI already running.

    ``-applaunch`` delegates display attachment to the running Steam
    desktop client; vrcpilot cannot bring the Steam UI up on its own
    (well outside this library's scope). The error signals to callers
    that the user must start Steam manually first.
    """


#: Linux Steam desktop client main-process name. The Steam launcher shell
#: script ``steam.sh`` execs into a native ``steam`` binary, so the
#: top-level process visible to ``psutil`` is named ``steam``. Child
#: helpers (``steamwebhelper``, ``steam-runtime-launcher-service``, ...) are
#: deliberately excluded by an exact-equality match.
_LINUX_STEAM_PROCESS_NAME: str = "steam"


def is_steam_running() -> bool:
    """Report whether the Steam desktop client process is alive on this host.

    Consulted only by the Linux ``via_steam=True`` preflight: Steam
    owns the X/Wayland display attachment for ``-applaunch``, so a
    missing UI guarantees launch failure. The probe runs on every
    platform but Windows callers ignore the result.
    """
    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] == _LINUX_STEAM_PROCESS_NAME:
            return True
    return False


_WINDOWS_STANDARD_PATHS: tuple[Path, ...] = (
    Path("C:/Program Files (x86)/Steam/Steam.exe"),
    Path("C:/Program Files/Steam/Steam.exe"),
)


def _find_steam_on_windows() -> Path:
    """Locate ``Steam.exe`` on Windows via the registry or standard paths."""
    # sys.platform == "win32" narrows so pyright resolves the Windows-only
    # winreg stubs from typeshed; without the guard the imports are unknown
    # on POSIX type-check runs.
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"
            ) as key:
                value, _ = winreg.QueryValueEx(key, "SteamPath")
            if isinstance(value, str):
                steam_path = Path(value) / "Steam.exe"
                if steam_path.is_file():
                    return steam_path
        except OSError:
            pass

    for candidate in _WINDOWS_STANDARD_PATHS:
        if candidate.is_file():
            return candidate

    raise SteamNotFoundError(
        "Steam.exe was not found in registry or standard install paths"
    )


def _find_steam_on_linux() -> Path:
    """Locate the ``steam`` command on Linux via ``PATH`` lookup."""
    located = shutil.which("steam")
    if located is None:
        raise SteamNotFoundError("'steam' command not found in PATH")
    return Path(located)


def find_steam_executable(override: Path | None = None) -> Path:
    """Resolve a Steam executable path that callers can spawn directly.

    Args:
        override: Pre-validated path the caller wants used verbatim
            (e.g. a non-standard install). Auto-detection is bypassed
            entirely; the path is only checked for ``is_file()`` so
            ``launch()`` does not later fail with a confusing
            ``FileNotFoundError`` from ``subprocess``.

    Raises:
        SteamNotFoundError: ``override`` was given but does not exist,
            auto-detection found no Steam install on this host, or the
            current platform is neither Windows nor Linux.
    """
    if override is not None:
        if override.is_file():
            return override
        raise SteamNotFoundError(
            f"Specified Steam executable does not exist: {override}"
        )

    if sys.platform == "win32":
        return _find_steam_on_windows()
    if sys.platform.startswith("linux"):
        return _find_steam_on_linux()

    raise SteamNotFoundError(f"Unsupported platform: {sys.platform}")
