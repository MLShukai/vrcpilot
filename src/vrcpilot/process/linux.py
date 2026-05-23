"""Linux-only helpers for :mod:`vrcpilot.process`."""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError("vrcpilot.process.linux is Linux-only")

import shutil
from pathlib import Path

from . import UmuLauncherNotFoundError


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
            "umu-run not found on PATH. Install umu-launcher: "
            "Ubuntu/Debian users should download the .deb from "
            "https://github.com/Open-Wine-Components/umu-launcher/releases/latest "
            "and run 'sudo apt install ./umu-launcher_*.deb'. "
            "Other distributions: see "
            "https://github.com/Open-Wine-Components/umu-launcher "
            "for build/install instructions. "
            "Alternatively, pass --via-steam to use steam.exe -applaunch."
        )
    return Path(located)
