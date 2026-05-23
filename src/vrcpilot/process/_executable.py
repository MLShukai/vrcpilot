"""VRChat launch.exe と umu-launcher の auto-discovery。

VRChat の起動は EAC ラッパー ``launch.exe`` を経由する必要がある (VRChat.exe を
直接叩くと offline mode になる)。Steam library にインストールされた
``steamapps/common/VRChat/launch.exe`` をプラットフォーム別に探す。

Linux で umu-launcher 経由起動を行うケースのため、``umu-run`` 実行ファイルの
PATH 探索ヘルパもここに同居させる。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from vrcpilot.process import UmuLauncherNotFoundError, VRChatLauncherNotFoundError

#: launch.exe の Steam 配下相対パス。
_LAUNCHER_RELATIVE: Path = Path("steamapps/common/VRChat/launch.exe")

#: $VRCHAT_LAUNCHER 環境変数名。
_LAUNCHER_ENV_VAR: str = "VRCHAT_LAUNCHER"


def _parse_steam_library_paths(vdf_path: Path) -> list[Path]:
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


def _windows_steam_paths() -> list[Path]:
    """Return candidate Steam install roots on Windows.

    Combines registry lookup, libraryfolders.vdf entries, and standard
    install paths in that priority order. The list may contain
    duplicates; callers de-duplicate while preserving order.
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

    # Expand via libraryfolders.vdf
    for root in list(candidates):
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            candidates.extend(_parse_steam_library_paths(vdf))

    candidates.extend(
        [
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
        ]
    )
    return candidates


def _linux_steam_paths() -> list[Path]:
    """Return candidate Steam install roots on Linux."""
    candidates: list[Path] = [
        Path("~/.steam/steam").expanduser(),
        Path("~/.local/share/Steam").expanduser(),
    ]
    for root in list(candidates):
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            candidates.extend(_parse_steam_library_paths(vdf))
    return candidates


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
        roots = _windows_steam_paths()
    elif sys.platform == "linux":
        roots = _linux_steam_paths()
    else:
        roots = []

    # ``roots`` are Steam install roots, but each one may also reference
    # additional library locations through its ``steamapps/libraryfolders.vdf``.
    # Expand here so callers (and the platform-specific helpers) need not
    # duplicate the discovery — every reachable Steam library is then probed
    # for ``steamapps/common/VRChat/launch.exe``.
    expanded: list[Path] = []
    seen_roots: set[Path] = set()
    for root in roots:
        if root in seen_roots:
            continue
        seen_roots.add(root)
        expanded.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            for library in _parse_steam_library_paths(vdf):
                if library not in seen_roots:
                    seen_roots.add(library)
                    expanded.append(library)

    seen: set[Path] = set()
    for root in expanded:
        candidate = root / _LAUNCHER_RELATIVE
        if candidate in seen:
            continue
        seen.add(candidate)
        result = _accept(candidate)
        if result is not None:
            return result

    raise VRChatLauncherNotFoundError(
        "VRChat launch.exe could not be located in any Steam library. "
        f"Tried: {[str(p) for p in tried]}. "
        "Pass --vrchat-launcher <path> or set $VRCHAT_LAUNCHER."
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
            "umu-run not found on PATH. Install umu-launcher from "
            "https://github.com/Open-Wine-Components/umu-launcher "
            "or pass --via-steam to use steam.exe -applaunch instead."
        )
    return Path(located)
