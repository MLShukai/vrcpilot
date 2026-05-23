"""VRChat launch flow.

デフォルトでは VRChat の ``launch.exe`` (EAC ラッパー) を直接 spawn する。Windows は
そのまま、Linux は ``umu-launcher`` (``umu-run``) 経由で起動。``via_steam=True`` を
渡すと従来の ``steam.exe -applaunch`` 経路にフォールバックする (既存 VRChat が動いて
いれば :class:`VRChatAlreadyRunningError` — Steam は同一インスタンスにフォーカスを
移すだけなので意図した新規起動ができないため)。

``launch.exe`` を経由する理由: ``VRChat.exe`` を直接叩くと EAC が初期化されず
offline モード起動になる。EAC ラッパー ``launch.exe`` が VRChat 用の正規エントリ
ポイント。

launch 後の PID 検出は launch 前 PID 集合との差分で行う。これにより既に他の VRChat
が動いていても、launch で生まれた新規 PID を確実に返せる。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import (
    PID_WAIT_INTERVAL,
    PID_WAIT_TIMEOUT,
    VRCHAT_STEAM_APP_ID,
)


@dataclass(frozen=True)
class OscConfig:
    """Structured form of VRChat's ``--osc=<in>:<ip>:<out>`` launch flag.

    Defaults mirror VRChat's factory OSC settings, so ``OscConfig()``
    forwards the flag explicitly without changing client semantics —
    useful when a deterministic argv is wanted (logging, tests).
    """

    in_port: int = 9000
    out_ip: str = "127.0.0.1"
    out_port: int = 9001

    def to_launch_arg(self) -> str:
        """Render as a single ``--osc=...`` argv token."""
        return f"--osc={self.in_port}:{self.out_ip}:{self.out_port}"


def build_vrchat_launch_args(
    *,
    no_vr: bool = False,
    screen_width: int | None = None,
    screen_height: int | None = None,
    osc: OscConfig | None = None,
    profile: int | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Assemble the VRChat-side argv that follows ``-applaunch <app_id>``.

    Output order is fixed (``no_vr`` -> screen size -> ``osc`` ->
    ``--profile`` -> ``extra_args``) so the argv is byte-stable across
    runs. ``extra_args`` is the escape hatch for flags this helper does
    not model. ``profile`` is rendered as the single ``--profile=N``
    token (the format VRChat accepts).
    """
    args: list[str] = []
    if no_vr:
        args.append("--no-vr")
    if screen_width is not None:
        args.extend(["-screen-width", str(screen_width)])
    if screen_height is not None:
        args.extend(["-screen-height", str(screen_height)])
    if osc is not None:
        args.append(osc.to_launch_arg())
    if profile is not None:
        args.append(f"--profile={profile}")
    if extra_args:
        args.extend(extra_args)
    return args


def build_launch_command(
    steam_executable: Path,
    app_id: int = VRCHAT_STEAM_APP_ID,
    *,
    vrchat_args: list[str] | None = None,
) -> list[str]:
    """Build the Steam ``-applaunch`` argv for spawning the game.

    Exposed separately from :func:`launch` so callers can inspect, log,
    or wrap the command without spawning. ``steam_executable`` is not
    validated by this helper.
    """
    cmd = [str(steam_executable), "-applaunch", str(app_id)]
    if vrchat_args:
        cmd.extend(vrchat_args)
    return cmd


def validate_launch_args(
    *,
    via_steam: bool,
    wineprefix: Path | None,
    proton_path: Path | None,
    profile: int | None,
) -> None:
    """``launch()`` 引数の fail-fast バリデーション.

    ``profile`` は両 platform で許容する (Windows でも VRChat の
    ``--profile=N`` argv を直接渡せる)。``wineprefix`` / ``proton_path``
    は Linux + direct-spawn 専用。``via_steam`` との同時指定は ``profile``
    を含めて禁止 — Steam 経由は ``--profile`` の伝達経路が異なる
    (Steam の launch options 側で持つべき) ため、ここで argv に注入する
    と二重指定や見落としを招く。
    """
    if profile is not None and profile < 0:
        raise ValueError(f"profile must be non-negative (got {profile})")

    direct_spawn_only = (
        wineprefix is not None or proton_path is not None or profile is not None
    )
    if direct_spawn_only and via_steam:
        raise ValueError(
            "wineprefix/proton_path/profile are only meaningful with "
            "direct-spawn (not --via-steam)"
        )
    if sys.platform == "win32" and (wineprefix is not None or proton_path is not None):
        raise ValueError("wineprefix/proton_path are Linux-only")


def _wait_for_new_pid(
    pre_pids: set[int],
    *,
    timeout: float,
    interval: float,
) -> int | None:
    """Launch 前後の PID 集合差分から新規 PID を返す.

    :func:`find_pids` が新しい順なので、複数の新規 PID があれば最新の 1 つを返す
    (通常はそもそも 1 つしか増えないが、race 対策で先頭採用)。
    """
    # ``process/__init__.py`` <-> ``launch.py`` の循環を断つため遅延 import。
    from . import find_pids

    deadline = time.monotonic() + timeout
    while True:
        current = find_pids()
        new_pids = [p for p in current if p not in pre_pids]
        if new_pids:
            return new_pids[0]
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def launch(
    *,
    via_steam: bool = False,
    app_id: int = VRCHAT_STEAM_APP_ID,
    steam_path: Path | None = None,
    vrchat_launcher: Path | None = None,
    wineprefix: Path | None = None,
    proton_path: Path | None = None,
    profile: int | None = None,
    no_vr: bool = False,
    screen_width: int | None = None,
    screen_height: int | None = None,
    osc: OscConfig | None = None,
    extra_args: list[str] | None = None,
    wait_timeout: float = PID_WAIT_TIMEOUT,
    wait_interval: float = PID_WAIT_INTERVAL,
) -> int | None:
    """Launch VRChat and (optionally) wait for the new PID to appear.

    Default path spawns VRChat's ``launch.exe`` (the EAC wrapper bundled
    alongside ``VRChat.exe``) directly. Calling ``VRChat.exe`` itself would
    boot in offline mode because EAC is not initialized — so ``launch.exe``
    is the required entry point. On Linux the spawn goes through
    ``umu-run`` (auto-discovered from PATH) to host the Wine/Proton runtime.

    Pass ``via_steam=True`` to fall back to the legacy
    ``steam.exe -applaunch <app_id>`` route. That path fails fast with
    :class:`VRChatAlreadyRunningError` if VRChat is already running because
    Steam will just refocus the existing instance instead of spawning a
    new one, defeating the purpose of a "launch" call.

    Args:
        via_steam: Use ``steam.exe -applaunch`` instead of direct spawn.
            Mutually exclusive with ``wineprefix`` / ``proton_path`` /
            ``profile``.
        app_id: Steam app id used by ``-applaunch`` (``via_steam=True`` route
            only). The direct-spawn route does **not** forward this as
            ``$GAMEID`` to ``umu-run``; see the in-function comment for the
            reason (umu-launcher's "global defaults" protonfix collides with
            VRChat's DLL surface, 2026-05-23).
        steam_path: Override Steam executable auto-detection. Only used
            when ``via_steam=True``.
        vrchat_launcher: Override the ``launch.exe`` path. When ``None``,
            auto-discovered via Steam ``libraryfolders.vdf``
            (see :func:`vrcpilot.process.executable.find_vrchat_launcher`).
        wineprefix: Linux + direct-spawn only. Sets ``$WINEPREFIX`` for
            the ``umu-run`` subprocess.
        proton_path: Linux + direct-spawn only. Sets ``$PROTON_PATH``.
        profile: Pass ``--profile=N`` to VRChat (separates SaveData /
            cache folders). Must be a non-negative int. Accepted on both
            Windows and Linux. On Linux, additionally auto-generates a
            prefix at ``$XDG_DATA_HOME/vrcpilot/profiles/<profile>/wineprefix``
            (falls back to ``~/.local/share/...``) and uses that for
            ``$WINEPREFIX``; an explicit ``wineprefix`` overrides this.
            Not compatible with ``via_steam`` (the Steam route should
            carry ``--profile`` via Steam launch options instead).
        no_vr / screen_width / screen_height / osc / extra_args: Forwarded
            to VRChat's argv via :func:`build_vrchat_launch_args`.
        wait_timeout: Seconds to wait for the new VRChat PID to appear
            after spawning. ``<=0`` to skip the wait entirely.
        wait_interval: Polling interval for the PID wait.

    Returns:
        The newly-spawned VRChat PID, or ``None`` if the wait was skipped
        (``wait_timeout <= 0``) or timed out.

    Raises:
        SteamNotFoundError: ``via_steam=True`` but Steam not found.
        SteamNotRunningError: Linux + ``via_steam=True`` but the Steam
            desktop client is not running on the host.
        VRChatLauncherNotFoundError: ``launch.exe`` cannot be located.
        UmuLauncherNotFoundError: Linux but ``umu-run`` is missing from
            PATH.
        VRChatAlreadyRunningError: ``via_steam=True`` but VRChat is
            already running.
        VRChatDisplayNotAvailableError: Linux + direct-spawn but neither
            ``$DISPLAY`` nor ``$WAYLAND_DISPLAY`` is set (no graphical
            session attached).
        ValueError: Invalid argument combination (see
            :func:`validate_launch_args`).
    """
    # Deferred imports — intentional, do not hoist to module top:
    #
    # * ``find_steam_executable`` is imported here so each ``launch()``
    #   call resolves the *current* binding on ``vrcpilot.steam``. Tests
    #   monkeypatch ``vrcpilot.steam.find_steam_executable`` directly; if
    #   we hoisted this to a module-level ``from ... import ...`` the test
    #   patch would no longer reach the binding actually used here. Keep
    #   the lookup deferred so test patches against the source module are
    #   guaranteed to take effect.
    # * The ``from . import ...`` lines break the
    #   ``process/__init__.py`` <-> ``launch.py`` import cycle: the
    #   package re-exports :func:`launch`, so importing names from the
    #   package at module load time would deadlock.
    from vrcpilot.steam import find_steam_executable

    from . import VRChatAlreadyRunningError, find_pids
    from .executable import find_vrchat_launcher

    validate_launch_args(
        via_steam=via_steam,
        wineprefix=wineprefix,
        proton_path=proton_path,
        profile=profile,
    )
    if sys.platform == "linux":
        from .linux import preflight_linux_environment

        preflight_linux_environment(via_steam=via_steam)

    vrchat_args = build_vrchat_launch_args(
        no_vr=no_vr,
        screen_width=screen_width,
        screen_height=screen_height,
        osc=osc,
        profile=profile,
        extra_args=extra_args,
    )

    pre_pids: set[int] = set(find_pids())

    env_overrides: dict[str, str] = {}
    if via_steam:
        if pre_pids:
            raise VRChatAlreadyRunningError(
                "via_steam=True cannot reliably launch a new instance when "
                f"VRChat is already running (existing PIDs: {sorted(pre_pids)}); "
                "steam.exe -applaunch will refocus the existing instance"
            )
        steam_executable = find_steam_executable(steam_path)
        argv = build_launch_command(steam_executable, app_id, vrchat_args=vrchat_args)
    else:
        launcher = find_vrchat_launcher(vrchat_launcher)
        if sys.platform == "win32":
            argv = [str(launcher), *vrchat_args]
        elif sys.platform == "linux":
            from .linux import find_umu_launcher, profile_wineprefix

            umu_run = find_umu_launcher()
            argv = [str(umu_run), str(launcher), *vrchat_args]
            # GAMEID は意図的に渡さない。GAMEID=438100 を渡すと umu-launcher が
            # ProtonFixes の "global defaults" (VRChat 専用 fix は未登録) を当て、
            # その global defaults が UMU-Proton-latest では未実装の
            # coremessaging.dll.DllGetActivationFactory を呼んで wine が即死する
            # (2026-05-23 実機で観測)。GAMEID 未指定なら umu の素の default で
            # 起動して安定する。ProtonFixes に VRChat (438100) の正規 fix が
            # upstream に追加されたら戻す価値がある。
            if wineprefix is not None:
                env_overrides["WINEPREFIX"] = str(wineprefix)
            elif profile is not None:
                generated = profile_wineprefix(profile)
                generated.mkdir(parents=True, exist_ok=True)
                env_overrides["WINEPREFIX"] = str(generated)
            if proton_path is not None:
                env_overrides["PROTON_PATH"] = str(proton_path)
        else:
            raise NotImplementedError(
                f"launch() (direct spawn) is not supported on {sys.platform}"
            )

    popen_env: dict[str, str] | None = (
        {**os.environ, **env_overrides} if env_overrides else None
    )

    if sys.platform == "win32":
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            env=popen_env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            env=popen_env,
            start_new_session=True,
        )

    if wait_timeout <= 0:
        return None
    return _wait_for_new_pid(pre_pids, timeout=wait_timeout, interval=wait_interval)
