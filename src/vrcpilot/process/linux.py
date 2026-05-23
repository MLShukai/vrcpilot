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
    """Vrcpilot 管理の profile 番号に対応する ``$WINEPREFIX`` パスを返す。

    既存ディレクトリの存在は保証しない (呼び出し側で
    ``mkdir(parents=True, exist_ok=True)`` する)。
    """
    base = Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share").expanduser()
    return base / "vrcpilot" / "profiles" / str(profile) / "wineprefix"


def preflight_linux_environment(*, via_steam: bool) -> None:
    """Linux 限定の launch pre-flight (display / Steam の事前確認)。

    direct-spawn: ``umu-run`` + Wine は GUI セッションへ attach できないと
    block して進まない (SSH 経由などで $DISPLAY が無い環境で発生)。事前検出
    して :class:`VRChatDisplayNotAvailableError` を投げる方が、subprocess
    が永久に hang するより早く失敗できる。X11 / Wayland どちらでも実用上は
    動くので、$DISPLAY と $WAYLAND_DISPLAY のいずれかが立っていれば OK と
    する。

    via_steam: ``steam.exe -applaunch`` は Steam クライアントが既に起動して
    いることを前提とした call (Steam は自分の display attachment を持って
    いる)。vrcpilot からは Steam UI を立ち上げられないので、未起動なら
    :class:`SteamNotRunningError` を投げてユーザーに通知する。
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
