"""``vrcpilot linux-mic`` subcommand: manage the PipeWire virtual mic.

Wraps :mod:`vrcpilot.mic.linux` with three actions: ``register``
(persist + live load), ``unregister`` (remove + live unload), and
``status`` (config / runtime module / soundcard visibility). The
parent-subparser shape matches :mod:`vrcpilot.cli.osc`.

The top-level CLI only registers ``linux-mic`` when
``sys.platform == "linux"``; on other platforms this module is never
imported. The defensive ``ImportError`` guard below makes a direct
``import vrcpilot.cli.linux_mic`` off-Linux fail loudly.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError("vrcpilot.cli.linux_mic is Linux-only")

import argparse
from typing import cast

from vrcpilot.mic.base import LIBPULSE_HINT

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Wire ``linux-mic`` plus its three actions into the top-level CLI."""
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
            "module loaded, soundcard visibility."
        ),
    )


def _run_register(args: argparse.Namespace) -> int:
    """Execute the ``register`` action."""
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
    # Always print the VRChat-side setup hint; the persistent config is
    # the source of truth regardless of whether the runtime load
    # succeeded, so users still need this step.
    print(
        "In VRChat Audio settings, select 'Monitor of VRCPilot Virtual "
        "Mic' as the microphone input",
        file=sys.stderr,
    )
    return 0


def _run_unregister() -> int:
    """Execute the ``unregister`` action."""
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
    """Return ``(loaded, error)`` for whether PipeWire has the sink loaded.

    ``loaded`` is ``True`` iff a ``module-null-sink`` with
    ``sink_name=<sink_name>`` is currently in ``pulse.module_list()``.
    ``error`` carries a short description when the pulsectl probe
    itself failed (missing dependency, control-plane error); ``status``
    surfaces it alongside the ``not loaded`` answer so it never raises.

    Goes through :func:`vrcpilot.mic.linux.open_pulse_control` -- the
    seam ``register`` / ``unregister`` / ``status`` all share.
    """
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


def _soundcard_visible(sink_name: str) -> tuple[bool, str | None]:
    """Return ``(visible, error)`` for whether soundcard can see the sink.

    Goes through :func:`soundcard.get_speaker` so the match honours
    both ``Speaker.id`` (PipeWire surfaces the null-sink as
    ``id="VRCPilotMic"``) and ``Speaker.name`` (description-derived,
    e.g. ``"VRCPilot_Virtual_Mic"``). A name-only scan misses this
    divergence -- the regression an id-aware match fixed.

    ``error`` is set when the probe itself blew up (soundcard not
    installed, libpulse / WASAPI dlopen failure); callers print it
    alongside the ``not visible`` answer rather than raising.
    """
    try:
        import soundcard as sc  # pyright: ignore[reportMissingTypeStubs]
    except ImportError as exc:
        return False, f"soundcard not installed ({exc})"
    except OSError as exc:
        # soundcard raises OSError on import when the native backend
        # (libpulse on Linux, WASAPI on Windows) cannot be dlopened.
        return False, f"soundcard import failed ({exc}); {LIBPULSE_HINT}"

    try:
        sc.get_speaker(sink_name)  # pyright: ignore[reportUnknownMemberType]
    except LookupError:
        return False, None
    except OSError as exc:
        # libpulse / WASAPI sometimes dlopen lazily on first
        # enumeration; reuse the same hint for consistent guidance.
        return False, f"soundcard probe failed ({exc}); {LIBPULSE_HINT}"
    except Exception as exc:  # noqa: BLE001
        return False, f"get_speaker failed ({exc})"
    return True, None


def _run_status() -> int:
    """Execute the ``status`` action.

    Machine-readable state lands on stdout with a stable vocabulary
    (``present`` / ``absent`` for config, ``loaded`` / ``unavailable`` /
    ``not loaded`` for runtime, ``visible`` / ``unavailable`` /
    ``not visible`` for soundcard); ``unavailable`` is the fixed label
    whenever a probe itself blew up, and the matching stderr line
    carries the underlying ``error: <message>``. Splitting the streams
    keeps scripts free to ``grep`` stdout without parsing
    failure-detail parentheticals.
    """
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

    visible, sc_err = _soundcard_visible(VIRTUAL_MIC_SINK_NAME)
    if sc_err is not None:
        print("soundcard: unavailable")
        print(f"soundcard: error: {sc_err}", file=sys.stderr)
    else:
        print(f"soundcard: {'visible' if visible else 'not visible'}")

    return 0


def run(args: argparse.Namespace) -> int:
    """Dispatch the requested ``linux-mic`` action.

    Reaching this function already implies ``sys.platform == "linux"``
    because :mod:`vrcpilot.cli` only registers ``linux-mic`` in
    ``_COMMANDS`` on Linux and this module's import-time guard would
    have raised :class:`ImportError` otherwise.
    """
    match args.action:
        case "register":
            return _run_register(args)
        case "unregister":
            return _run_unregister()
        case "status":
            return _run_status()
        case _:  # pragma: no cover - argparse required=True prevents this
            raise AssertionError(f"Unknown linux-mic action: {args.action!r}")
