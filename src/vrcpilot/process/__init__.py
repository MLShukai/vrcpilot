"""VRChat process lifecycle: launch, find, terminate."""

from __future__ import annotations

from .errors import (
    UmuLauncherNotFoundError,
    VRChatAlreadyRunningError,
    VRChatDisplayNotAvailableError,
    VRChatLauncherNotFoundError,
    VRChatMultipleInstancesError,
    VRChatNotRunningError,
    VRChatSteamCompatdataNotFoundError,
)
from .launch import (
    VRCHAT_STEAM_APP_ID,
    OscConfig,
    build_launch_command,
    build_vrchat_launch_args,
    launch,
)
from .pid import (
    PID_WAIT_INTERVAL,
    PID_WAIT_TIMEOUT,
    VRCHAT_PROCESS_NAME,
    find_pid,
    find_pids,
    resolve_pid,
    terminate,
    wait_for_no_pid,
    wait_for_pid,
)

__all__ = [
    "build_launch_command",
    "build_vrchat_launch_args",
    "find_pid",
    "find_pids",
    "launch",
    "OscConfig",
    "PID_WAIT_INTERVAL",
    "PID_WAIT_TIMEOUT",
    "resolve_pid",
    "terminate",
    "UmuLauncherNotFoundError",
    "VRCHAT_PROCESS_NAME",
    "VRCHAT_STEAM_APP_ID",
    "VRChatAlreadyRunningError",
    "VRChatDisplayNotAvailableError",
    "VRChatLauncherNotFoundError",
    "VRChatMultipleInstancesError",
    "VRChatNotRunningError",
    "VRChatSteamCompatdataNotFoundError",
    "wait_for_no_pid",
    "wait_for_pid",
]
