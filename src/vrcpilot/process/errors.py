"""Public exception classes for :mod:`vrcpilot.process`."""

from __future__ import annotations


class VRChatNotRunningError(RuntimeError):
    """No VRChat process is running when an input was requested."""


class VRChatMultipleInstancesError(VRChatNotRunningError):
    """Raised when no pid is specified but multiple VRChat instances are
    running.

    Subclass of :class:`VRChatNotRunningError` so existing ``except`` blocks
    still catch it. The candidate PIDs are exposed via :attr:`pids` (newest
    first, matching :func:`vrcpilot.process.find_pids`'s ordering).
    """

    def __init__(self, pids: list[int]) -> None:
        super().__init__(
            f"multiple VRChat instances detected (PIDs: {pids}); "
            "pass pid= to disambiguate"
        )
        self.pids = list(pids)


class VRChatLauncherNotFoundError(RuntimeError):
    """Raised when VRChat's ``launch.exe`` (EAC wrapper) cannot be located."""


class VRChatAlreadyRunningError(RuntimeError):
    """Raised when ``launch(via_steam=True)`` is called while VRChat is already
    running.

    ``steam.exe -applaunch`` simply focuses the existing instance instead of
    spawning a new one, so the call would never observe a new PID.
    """


class UmuLauncherNotFoundError(RuntimeError):
    """Raised when Linux direct-spawn cannot find ``umu-run`` on PATH."""


class VRChatSteamCompatdataNotFoundError(RuntimeError):
    """Raised on Linux + direct-spawn + ``profile=0`` when the Steam-managed
    ``compatdata/<app_id>/pfx`` directory does not exist.

    ``profile=0`` opts into sharing the wineprefix that Steam itself uses
    for VRChat (so the launched session sees the same login / SaveData as a
    ``--via-steam`` run). That prefix only materialises after Steam has
    launched VRChat at least once; before then the path simply does not
    exist. We fail fast instead of silently falling back to a fresh prefix
    so the user is told to either run ``--via-steam`` once or pass
    ``--wineprefix`` explicitly.
    """


class VRChatDisplayNotAvailableError(RuntimeError):
    """Raised when ``launch()`` (direct-spawn) is invoked on Linux without a
    graphical display attached.

    The umu-run + Wine subprocess needs a display server to draw into.
    With neither ``$DISPLAY`` (X11 / XWayland) nor ``$WAYLAND_DISPLAY``
    (Wayland-native) set, umu-run does not fail fast — it hangs waiting
    for a server. vrcpilot detects this pre-spawn so callers (notably
    the e2e harness running over plain SSH) see an immediate, actionable
    error instead of a stuck process.

    Only the direct-spawn route is gated; ``via_steam=True`` delegates
    display setup to the already-running Steam desktop client and is
    instead pre-flighted by a Steam-process-running check.
    """
