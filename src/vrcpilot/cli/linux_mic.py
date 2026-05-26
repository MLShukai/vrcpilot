"""``vrcpilot linux-mic`` subcommand: manage the PipeWire virtual mic.

Linux-only because Windows uses VB-Audio Virtual Cable, which is a
user-space driver registered out-of-band; there is no Windows
analogue for the ``register`` / ``unregister`` / ``status`` actions.
The top-level CLI conditionally wires this subcommand only on Linux,
so ``vrcpilot --help`` on Windows never advertises a command that has
no Windows implementation. Importing this module on a non-Linux
platform raises :class:`ImportError` as a defensive secondary guard.
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
    """Wire ``linux-mic`` plus its three actions into the CLI."""
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
    register_parser.add_argument(
        "--suffix",
        default="",
        metavar="NAME",
        help=(
            "register a named additional sink (VRCPilotMic_<suffix>); "
            "default: VRCPilotMic"
        ),
    )

    unregister_parser = actions.add_parser(
        "unregister",
        help=(
            "Remove the PipeWire config fragment and unload any matching "
            "runtime module."
        ),
    )
    unregister_excl = unregister_parser.add_mutually_exclusive_group()
    unregister_excl.add_argument(
        "--suffix",
        default="",
        metavar="NAME",
        help="unregister a specific suffix (default: VRCPilotMic)",
    )
    unregister_excl.add_argument(
        "--all",
        action="store_true",
        help="unregister every vrcpilot-mic*.conf in the config directory",
    )

    status_parser = actions.add_parser(
        "status",
        help=(
            "Report current registration state: config present, runtime "
            "module loaded, soundcard visibility."
        ),
    )
    status_excl = status_parser.add_mutually_exclusive_group()
    status_excl.add_argument(
        "--suffix",
        default="",
        metavar="NAME",
        help="show status for a specific suffix (default: VRCPilotMic)",
    )
    status_excl.add_argument(
        "--all",
        action="store_true",
        help="show status for every registered suffix",
    )


def _run_register(args: argparse.Namespace) -> int:
    """Execute the ``register`` action."""
    from vrcpilot.mic import linux as mic_linux
    from vrcpilot.mic.base import description_for

    suffix = cast(str, args.suffix)
    try:
        result = mic_linux.register_virtual_mic(
            suffix=suffix,
            runtime_load=not args.no_runtime_load,
        )
    except ValueError as exc:
        print(f"vrcpilot: invalid suffix: {exc}", file=sys.stderr)
        return 2

    if result.created_config:
        print(f"Wrote PipeWire config to {result.config_path}", file=sys.stderr)
    else:
        print(
            f"PipeWire config already up to date at {result.config_path}",
            file=sys.stderr,
        )
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
    description = description_for(result.suffix)
    print(
        f"In VRChat Audio settings, select 'Monitor of {description}' "
        "as the microphone input",
        file=sys.stderr,
    )
    return 0


def _run_unregister(args: argparse.Namespace) -> int:
    """Execute the ``unregister`` action."""
    from vrcpilot.mic import linux as mic_linux

    if args.all:
        suffixes = mic_linux.iter_registered_suffixes()
        if not suffixes:
            print("No VRCPilotMic registrations to remove", file=sys.stderr)
            return 0
        for suffix in suffixes:
            mic_linux.unregister_virtual_mic(suffix=suffix)
            print(
                f"Removed VRCPilotMic config and/or runtime sink (suffix: {suffix})",
                file=sys.stderr,
            )
        return 0

    suffix = cast(str, args.suffix)
    try:
        removed = mic_linux.unregister_virtual_mic(suffix=suffix)
    except ValueError as exc:
        print(f"vrcpilot: invalid suffix: {exc}", file=sys.stderr)
        return 2

    if removed:
        print(
            "Removed VRCPilotMic config and/or runtime sink",
            file=sys.stderr,
        )
    else:
        print("No VRCPilotMic registration to remove", file=sys.stderr)
    return 0


def _runtime_loaded(sink_name: str) -> tuple[bool, str | None]:
    """Probe whether PipeWire currently has the named null-sink loaded.

    ``loaded`` is ``True`` iff a ``module-null-sink`` with
    ``sink_name=<sink_name>`` appears in ``pulse.module_list()``.
    ``error`` carries a short description when the pulsectl probe
    itself fails (missing dependency, control-plane error); ``status``
    surfaces it alongside the ``not loaded`` answer so this helper
    never raises out into the CLI.

    Goes through :func:`vrcpilot.mic.linux.open_pulse_control` — the
    shared seam ``register`` / ``unregister`` / ``status`` all use.
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
    """Probe whether ``soundcard`` can enumerate the named PipeWire sink.

    Goes through :func:`soundcard.get_speaker` so the match honours
    both ``Speaker.id`` (PipeWire surfaces the null-sink as
    ``id="VRCPilotMic"``) and ``Speaker.name`` (description-derived,
    e.g. ``"VRCPilot_Virtual_Mic"``). A name-only scan misses this
    divergence — the regression an id-aware match fixed.

    ``error`` is set when the probe itself blows up (soundcard not
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


def _print_status_block(suffix: str, *, include_suffix_header: bool) -> None:
    """Print one ``config / runtime / soundcard`` status block.

    ``include_suffix_header`` controls whether a leading ``suffix: ...``
    line is emitted. The empty-suffix, no-argument default path keeps
    its historical four-line output to preserve back-compat with
    existing pins.
    """
    from vrcpilot.mic import linux as mic_linux
    from vrcpilot.mic.base import sink_name_for

    if include_suffix_header:
        print(f"suffix: {suffix}")

    config_present = mic_linux.is_registered(suffix=suffix)
    cfg_path = mic_linux.config_path(suffix=suffix)
    print(f"config: {'present' if config_present else 'absent'}")
    print(f"config_path: {cfg_path}")

    sink_name = sink_name_for(suffix)

    loaded, runtime_err = _runtime_loaded(sink_name)
    if runtime_err is not None:
        print("runtime: unavailable")
        print(f"runtime: error: {runtime_err}", file=sys.stderr)
    else:
        print(f"runtime: {'loaded' if loaded else 'not loaded'}")

    visible, sc_err = _soundcard_visible(sink_name)
    if sc_err is not None:
        print("soundcard: unavailable")
        print(f"soundcard: error: {sc_err}", file=sys.stderr)
    else:
        print(f"soundcard: {'visible' if visible else 'not visible'}")


def _run_status(args: argparse.Namespace) -> int:
    """Execute the ``status`` action.

    Machine-readable state lands on stdout with a stable vocabulary
    (``present`` / ``absent`` for config, ``loaded`` / ``unavailable`` /
    ``not loaded`` for runtime, ``visible`` / ``unavailable`` /
    ``not visible`` for soundcard); ``unavailable`` is the fixed label
    whenever a probe itself blew up, and the matching stderr line
    carries the underlying ``error: <message>``. Splitting the streams
    lets scripts ``grep`` stdout without parsing failure-detail
    parentheticals.
    """
    from vrcpilot.mic import linux as mic_linux

    if args.all:
        suffixes = mic_linux.iter_registered_suffixes()
        if not suffixes:
            cfg_dir = mic_linux.config_path().parent
            print("suffix: (none)")
            print("config: absent")
            print(f"config_path: {cfg_dir}/")
            print(
                "No vrcpilot-mic config fragments found. "
                "Run 'vrcpilot linux-mic register' first.",
                file=sys.stderr,
            )
            return 0
        for idx, suffix in enumerate(suffixes):
            if idx > 0:
                print()
            _print_status_block(suffix, include_suffix_header=True)
        return 0

    suffix = cast(str, args.suffix)
    _print_status_block(suffix, include_suffix_header=bool(suffix))
    return 0


def run(args: argparse.Namespace) -> int:
    """Dispatch the requested ``linux-mic`` action.

    Reaching this function implies Linux; the module's import guard
    raises on every other platform.
    """
    match args.action:
        case "register":
            return _run_register(args)
        case "unregister":
            return _run_unregister(args)
        case "status":
            return _run_status(args)
        case _:  # pragma: no cover - argparse required=True prevents this
            raise AssertionError(f"Unknown linux-mic action: {args.action!r}")
