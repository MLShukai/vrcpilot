"""``vrcpilot speaker`` subcommand: list / route output devices.

Owns the output-side audio concern — which physical device a given
VRChat instance's audio plays into. Application-audio *capture* is a
separate concern owned by ``vrcpilot record``; this CLI does the
device-selection / per-PID relay half. See ``docs/virtual-audio.md``
for end-to-end usage scenarios (multi-instance routing, virtual-cable
setups).

Two actions:

* ``list`` — YAML inventory of output devices (default first, then
  name-sorted) on stdout.
* ``route`` — open a PID-scoped audio relay to a chosen output device
  and block until ``Ctrl+C``.

Unlike most PID-dependent subcommands, ``route`` requires ``--pid``
explicitly; multi-instance handling is the entire reason this command
exists, so silently picking a single instance via
:func:`vrcpilot.cli._common.add_pid_arg` would defeat the point.
"""

from __future__ import annotations

import argparse
import sys
import time

from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.speaker.routing import (
    AudioRoutingError,
    DeviceNotFoundError,
    list_devices,
    route,
)

from ._common import SubParsersAction, emit_yaml

#: Exceptions the spec (§4.3 exit-code table) maps to exit 1 with a
#: single ``vrcpilot: <msg>`` stderr line. ``DeviceNotFoundError`` /
#: ``AudioRoutingError`` are ``RuntimeError`` subclasses, so the bare
#: ``RuntimeError`` entry would suffice — they are listed explicitly to
#: pin the contract to the spec and surface it to readers.
_ROUTE_RUNTIME_ERRORS: tuple[type[BaseException], ...] = (
    DeviceNotFoundError,
    AudioRoutingError,
    VRChatMultipleInstancesError,
    RuntimeError,
    OSError,
    ImportError,
    NotImplementedError,
)


def register(subparsers: SubParsersAction) -> None:
    """Wire ``speaker`` plus its ``list`` / ``route`` actions."""
    parser = subparsers.add_parser(
        "speaker",
        help=(
            "List output audio devices, or relay one VRChat instance's "
            "audio to a chosen output device."
        ),
    )
    actions = parser.add_subparsers(dest="speaker_action", required=True)

    actions.add_parser(
        "list",
        help="List output audio devices as YAML on stdout.",
    )

    route_parser = actions.add_parser(
        "route",
        help=("Relay one VRChat PID's audio to an output device until Ctrl+C."),
    )
    # ``--pid`` is required for ``route`` per spec §4.4, so the shared
    # ``add_pid_arg`` helper (which makes ``--pid`` optional and falls
    # back to single-instance resolution) deliberately is NOT used.
    route_parser.add_argument(
        "--pid",
        type=int,
        required=True,
        metavar="PID",
        help="Target VRChat PID whose audio should be relayed.",
    )
    route_parser.add_argument(
        "--device",
        type=str,
        default=None,
        metavar="QUERY",
        help=(
            "Output device query (id / name exact / case-insensitive "
            "substring). Defaults to the system default speaker."
        ),
    )
    route_parser.add_argument(
        "--chunk-seconds",
        type=float,
        default=0.02,
        metavar="SECONDS",
        dest="chunk_seconds",
        help="SpeakerLoop chunk size in seconds. Default: 0.02.",
    )
    route_parser.add_argument(
        "--blocksize",
        type=int,
        default=None,
        metavar="FRAMES",
        help="soundcard player blocksize in frames. Default: None.",
    )


def _run_list() -> int:
    """Emit the device-list YAML on stdout.

    Returns 0 on success, or 1 with a single ``vrcpilot: <msg>``
    stderr line when device enumeration itself fails (missing audio
    backend, soundcard import failure, ``AudioRoutingError``).
    """
    try:
        devices = list_devices()
    except (OSError, ImportError, AudioRoutingError) as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1

    payload: dict[str, object] = {
        "devices": [
            {"id": d.id, "name": d.name, "is_default": d.is_default} for d in devices
        ]
    }
    emit_yaml(payload)
    return 0


def _run_route(args: argparse.Namespace) -> int:
    """Open a PID-scoped relay and block until ``Ctrl+C`` or failure.

    Prints a single ``route: pid=<PID> device=<NAME!r>`` summary to
    stderr on entry, appending `` (system default)`` when ``--device``
    was omitted, then sleeps in 500 ms ticks so SIGINT lands on the
    Python interpreter promptly. ``KeyboardInterrupt`` is the
    nominal exit path (return 0); :data:`_ROUTE_RUNTIME_ERRORS` collapse
    to exit 1 with a single ``vrcpilot: <msg>`` stderr line.
    """
    pid: int = args.pid
    device: str | None = args.device

    try:
        with route(
            pid,
            device,
            chunk_seconds=args.chunk_seconds,
            blocksize=args.blocksize,
        ) as router:
            suffix = " (system default)" if device is None else ""
            print(
                f"route: pid={pid} device={router.device.name!r}{suffix}",
                file=sys.stderr,
            )
            # ``KeyboardInterrupt`` here propagates through Router's
            # ``__exit__`` (which stops the relay) and is caught by the
            # outer handler below — same clean-exit path used when SIGINT
            # arrives during ``Router.start()``.
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    except _ROUTE_RUNTIME_ERRORS as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1

    return 0


def run(args: argparse.Namespace) -> int:
    """Dispatch to the requested ``speaker`` action."""
    if args.speaker_action == "list":
        return _run_list()
    return _run_route(args)
