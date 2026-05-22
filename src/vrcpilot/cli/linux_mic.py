"""``vrcpilot linux-mic`` subcommand.

Manage the persistent ``VRCPilotMic`` virtual mic that
:mod:`vrcpilot.mic.linux` installs into PipeWire. Three actions:

* ``register`` -- write the PipeWire config fragment and (unless
  ``--no-runtime-load`` is passed) load ``module-null-sink`` now so the
  sink is usable in the current session.
* ``unregister`` -- remove the config fragment and unload any matching
  runtime module.
* ``status`` -- report what is currently in place: config file, runtime
  module, and whether ``sounddevice`` can see the device.

The action sits under a single parent subparser so the top-level CLI
exposes only ``linux-mic`` (the actions live one level deeper, matching
the structure of :mod:`vrcpilot.cli.osc`).

Non-Linux invocations short-circuit with exit code ``2`` and a hint
pointing Windows users at VB-Cable. :mod:`vrcpilot.mic.linux` is
imported lazily inside :func:`run` so this module itself stays
importable on every platform (the top-level CLI dispatcher constructs
the parser unconditionally).
"""

from __future__ import annotations

import argparse
import sys
from typing import cast

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Add the ``linux-mic`` parent subparser plus its three actions."""
    parser = subparsers.add_parser(
        "linux-mic",
        help=(
            "Manage the VRCPilotMic PipeWire virtual mic on Linux "
            "(register / unregister / status). Windows uses VB-Cable, "
            "see docs/usage.md."
        ),
    )
    actions = parser.add_subparsers(dest="action", required=True)

    register_parser = actions.add_parser(
        "register",
        help=(
            "Write the persistent PipeWire config and (by default) load "
            "the null-sink immediately."
        ),
    )
    register_parser.add_argument(
        "--no-runtime-load",
        action="store_true",
        help=(
            "Skip the immediate pulsectl module_load step (config is "
            "still written; restart PipeWire to pick it up)."
        ),
    )

    actions.add_parser(
        "unregister",
        help=(
            "Remove the PipeWire config fragment and unload any matching "
            "runtime module."
        ),
    )

    actions.add_parser(
        "status",
        help=(
            "Report current registration state: config present, runtime "
            "module loaded, sounddevice visibility."
        ),
    )


def _run_register(args: argparse.Namespace) -> int:
    """Execute the ``register`` action."""
    # Lazy: top-level import raises on non-Linux; the OS guard above
    # must short-circuit first.
    from vrcpilot.mic import linux as mic_linux

    result = mic_linux.register_virtual_mic(runtime_load=not args.no_runtime_load)
    print(f"Wrote PipeWire config to {result.config_path}", file=sys.stderr)
    if result.runtime_loaded:
        print("Loaded module-null-sink immediately", file=sys.stderr)
    elif result.runtime_warning is not None:
        print(f"warning: {result.runtime_warning}", file=sys.stderr)
        print(
            "Restart PipeWire to pick up the config: "
            "systemctl --user restart pipewire pipewire-pulse wireplumber",
            file=sys.stderr,
        )
    # Always print the next-step guidance so users discover the VRChat
    # setting; persistent config is the source of truth regardless of
    # whether the runtime load succeeded.
    print(
        "In VRChat Audio settings, select 'Monitor of VRCPilot Virtual "
        "Mic' as the microphone input",
        file=sys.stderr,
    )
    return 0


def _run_unregister() -> int:
    """Execute the ``unregister`` action."""
    # Lazy: top-level import raises on non-Linux; the OS guard above
    # must short-circuit first.
    from vrcpilot.mic import linux as mic_linux

    removed = mic_linux.unregister_virtual_mic()
    if removed:
        print(
            "Removed VRCPilotMic config and/or runtime sink",
            file=sys.stderr,
        )
    else:
        print("No VRCPilotMic registration to remove", file=sys.stderr)
    return 0


def _runtime_loaded(sink_name: str) -> tuple[bool, str | None]:
    """Return ``(loaded, error)`` from inspecting ``pulsectl`` modules.

    ``loaded`` is ``True`` iff a ``module-null-sink`` is currently
    loaded whose ``argument`` contains ``sink_name=<sink_name>``.
    ``error`` carries a short human-readable description when the
    pulsectl probe itself failed (missing dependency, control-plane
    error); the caller surfaces this alongside the ``not loaded``
    answer so ``status`` never raises.

    Uses :func:`vrcpilot.mic.linux.open_pulse_control` so the
    ``register`` / ``unregister`` / ``status`` paths all funnel through
    the same seam -- unit tests can patch one symbol and cover all three.
    """
    # Lazy: top-level import raises on non-Linux; the OS guard above
    # must short-circuit first.
    from vrcpilot.mic import linux as mic_linux

    try:
        pulse = mic_linux.open_pulse_control("vrcpilot-mic-status")
    except ImportError as exc:
        return False, f"pulsectl not installed ({exc})"
    except Exception as exc:  # noqa: BLE001
        return False, f"could not open pulsectl ({exc})"

    try:
        try:
            modules = pulse.module_list()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        except Exception as exc:  # noqa: BLE001
            return False, f"module_list failed ({exc})"
        needle = f"sink_name={sink_name}"
        for module in modules:  # pyright: ignore[reportUnknownVariableType]
            module_obj = cast(object, module)
            name = getattr(module_obj, "name", None)
            arg = getattr(module_obj, "argument", None) or ""
            if name == "module-null-sink" and needle in arg:
                return True, None
    finally:
        try:
            pulse.close()  # pyright: ignore[reportUnknownMemberType]
        except Exception:  # noqa: BLE001
            pass
    return False, None


def _sounddevice_visible(sink_name: str) -> tuple[bool, str | None]:
    """Return ``(visible, error)`` from a sounddevice device probe.

    ``visible`` is ``True`` iff some entry from
    ``sounddevice.query_devices()`` contains ``sink_name`` as a
    substring of its ``name`` field. ``error`` is populated when the
    probe itself blew up (sounddevice missing, PortAudio open failure);
    callers print it alongside the ``not visible`` answer.
    """
    try:
        import sounddevice as sd  # pyright: ignore[reportMissingTypeStubs]
    except ImportError as exc:
        return False, f"sounddevice not installed ({exc})"
    except OSError as exc:
        # sounddevice raises OSError on import when the PortAudio shared
        # library is missing (libportaudio2 on Debian/Ubuntu, portaudio
        # on Fedora). Surface a hint along with the underlying error.
        return False, (
            f"sounddevice import failed ({exc}); install PortAudio "
            "(e.g. 'sudo apt-get install libportaudio2')"
        )

    try:
        devices = sd.query_devices()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    except Exception as exc:  # noqa: BLE001
        return False, f"query_devices failed ({exc})"

    for device in devices:  # pyright: ignore[reportUnknownVariableType]
        device_obj = cast(object, device)
        name = ""
        if isinstance(device_obj, dict):
            raw = device_obj.get("name", "")  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
            if isinstance(raw, str):
                name = raw
        else:
            attr = getattr(device_obj, "name", "")
            if isinstance(attr, str):
                name = attr
        if sink_name in name:
            return True, None
    return False, None


def _run_status() -> int:
    """Execute the ``status`` action.

    Machine-readable state lands on stdout in a stable vocabulary
    (``present``/``absent`` for config, ``loaded``/``unavailable``/
    ``not loaded`` for runtime, ``visible``/``unavailable``/``not
    visible`` for sounddevice); human-readable error detail goes to
    stderr so scripts can ``grep`` stdout without seeing import-failure
    parentheticals. ``unavailable`` is the fixed label used whenever
    the probe itself blew up; the matching stderr line carries the
    underlying ``error: <message>``.
    """
    # Lazy: top-level import raises on non-Linux; the OS guard above
    # must short-circuit first.
    from vrcpilot.mic import linux as mic_linux
    from vrcpilot.mic.base import VIRTUAL_MIC_SINK_NAME

    config_present = mic_linux.is_registered()
    cfg_path = mic_linux.config_path()

    print(f"config: {'present' if config_present else 'absent'}")
    print(f"config_path: {cfg_path}")

    loaded, runtime_err = _runtime_loaded(VIRTUAL_MIC_SINK_NAME)
    if runtime_err is not None:
        print("runtime: unavailable")
        print(f"runtime: error: {runtime_err}", file=sys.stderr)
    else:
        print(f"runtime: {'loaded' if loaded else 'not loaded'}")

    visible, sd_err = _sounddevice_visible(VIRTUAL_MIC_SINK_NAME)
    if sd_err is not None:
        print("sounddevice: unavailable")
        print(f"sounddevice: error: {sd_err}", file=sys.stderr)
    else:
        print(f"sounddevice: {'visible' if visible else 'not visible'}")

    return 0


def run(args: argparse.Namespace) -> int:
    """Dispatch the requested ``linux-mic`` action.

    On non-Linux platforms returns exit code ``2`` with a hint pointing
    at the Windows alternative; this is a CLI-entry guard rather than
    an architectural cross-platform claim, so the ``sys.platform``
    check stays here and :mod:`vrcpilot.mic.linux` is imported lazily
    inside the per-action helpers.
    """
    if sys.platform != "linux":
        print(
            "vrcpilot: linux-mic is Linux-only; Windows uses VB-Cable, "
            "see docs/usage.md",
            file=sys.stderr,
        )
        return 2

    match args.action:
        case "register":
            return _run_register(args)
        case "unregister":
            return _run_unregister()
        case "status":
            return _run_status()
        case _:  # pragma: no cover - argparse required=True prevents this
            raise AssertionError(f"Unknown linux-mic action: {args.action!r}")
