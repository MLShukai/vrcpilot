"""Steam executable discovery and runtime-state probing."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import psutil


class SteamNotFoundError(RuntimeError):
    """Raised when the Steam executable cannot be located."""


class SteamNotRunningError(RuntimeError):
    """Raised when ``launch(via_steam=True)`` is invoked on Linux but the Steam
    client process is not running.

    The Steam ``-applaunch`` route delegates display setup to the
    already-running Steam desktop client; vrcpilot has no way to spin up the
    full Steam UI itself (and doing so would be far outside this library's
    scope). Surface the constraint to the caller so the user knows to start
    Steam manually.
    """


#: Linux Steam desktop client main-process name. The Steam launcher shell
#: script ``steam.sh`` execs into a native ``steam`` binary, so the
#: top-level process visible to ``psutil`` is named ``steam``. Child
#: helpers (``steamwebhelper``, ``steam-runtime-launcher-service``, ...) are
#: deliberately excluded by an exact-equality match.
_LINUX_STEAM_PROCESS_NAME: str = "steam"


def is_steam_running() -> bool:
    """Return ``True`` when the Steam desktop client is alive on this host.

    Linux is the only platform where vrcpilot actually consults this (the
    ``via_steam=True`` Linux preflight needs the user's Steam UI to already
    be up because Steam is what owns the X/Wayland display attachment).
    The implementation is platform-agnostic — it just enumerates processes
    via :mod:`psutil` — but on Windows the answer is unused by vrcpilot.
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
    """Return the verified Steam executable path for the current platform.

    When ``override`` is given it is validated and returned without
    auto-detection. Raises :class:`SteamNotFoundError` when ``override``
    does not exist, auto-detection fails, or the platform is unsupported.
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
