"""VRChat ``launch.exe`` の auto-discovery。

VRChat の起動は EAC ラッパー ``launch.exe`` を経由する必要がある (VRChat.exe を
直接叩くと offline mode になる)。Steam library にインストールされた
``steamapps/common/VRChat/launch.exe`` をプラットフォーム別に探す。

Linux 限定の umu-launcher 探索は :mod:`vrcpilot.process.linux` に分離。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from vrcpilot.process import VRChatLauncherNotFoundError

#: launch.exe の Steam 配下相対パス。
_LAUNCHER_RELATIVE: Path = Path("steamapps/common/VRChat/launch.exe")

#: $VRCHAT_LAUNCHER 環境変数名。
_LAUNCHER_ENV_VAR: str = "VRCHAT_LAUNCHER"


def parse_steam_library_paths(vdf_path: Path) -> list[Path]:
    """``libraryfolders.vdf`` から各 library の root path を抽出。

    フル VDF パーサは過剰なので、``"path" "<value>"`` の正規表現抽出だけ行う。
    値が Windows 形式のバックスラッシュ込みパスでも、Path(...) に渡せば後段の
    ``is_file()`` で適切に判定される (Linux 上の Path で Windows パスを
    解釈しようとすると false になり、結果として candidate がスキップされる)。
    """
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
    tried: list[Path] = []

    def _accept(candidate: Path) -> Path | None:
        tried.append(candidate)
        return candidate if candidate.is_file() else None

    if override is not None:
        result = _accept(override)
        if result is not None:
            return result
        raise VRChatLauncherNotFoundError(
            f"VRChat launch.exe not found at override path: {override}"
        )

    env_value = os.environ.get(_LAUNCHER_ENV_VAR)
    if env_value:
        result = _accept(Path(env_value))
        if result is not None:
            return result

    if sys.platform == "win32":
        roots = windows_steam_paths()
    elif sys.platform == "linux":
        roots = linux_steam_paths()
    else:
        roots = []

    # Single source of truth for Steam library discovery: each ``root``
    # returned by the platform helper is a Steam *install root*, and the
    # real library locations live in ``steamapps/libraryfolders.vdf`` under
    # that root. The helpers deliberately do **not** expand the vdf so the
    # expansion happens in exactly one place. If the vdf is missing (fresh
    # install or non-standard layout) we fall back to ``root`` itself, which
    # also holds ``steamapps/common/VRChat/launch.exe`` for single-library
    # setups.
    seen_libraries: set[Path] = set()
    libraries: list[Path] = []

    def _add_library(library: Path) -> None:
        if library in seen_libraries:
            return
        seen_libraries.add(library)
        libraries.append(library)

    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            for library in parse_steam_library_paths(vdf):
                _add_library(library)
        else:
            _add_library(root)

    seen_candidates: set[Path] = set()
    for library in libraries:
        candidate = library / _LAUNCHER_RELATIVE
        if candidate in seen_candidates:
            continue
        seen_candidates.add(candidate)
        result = _accept(candidate)
        if result is not None:
            return result

    raise VRChatLauncherNotFoundError(
        "VRChat launch.exe could not be located in any Steam library. "
        f"Tried: {[str(p) for p in tried]}. "
        "Pass --vrchat-launcher <path> or set $VRCHAT_LAUNCHER."
    )
