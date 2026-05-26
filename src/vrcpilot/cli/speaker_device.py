"""``vrcpilot speaker-device`` subcommand: list / route output devices.

Two actions:

* ``list`` — emits a YAML payload describing every available output
  speaker (default first, then name-sorted) to stdout.
* ``route`` — opens a PID-scoped audio relay from one VRChat instance
  to a chosen output device and blocks until ``Ctrl+C``.

Unlike most PID-dependent subcommands, ``route`` requires ``--pid``;
the spec calls for explicit multi-instance handling so we do **not**
go through :func:`vrcpilot.cli._common.add_pid_arg` here.
"""

from __future__ import annotations

import argparse
import sys
import time

import yaml

from vrcpilot.process import VRChatMultipleInstancesError
from vrcpilot.speaker.routing import (
    AudioRoutingError,
    DeviceNotFoundError,
    list_devices,
    route,
)

from ._common import SubParsersAction


def register(subparsers: SubParsersAction) -> None:
    """Wire ``speaker-device`` plus its ``list`` / ``route`` actions."""
    parser = subparsers.add_parser(
        "speaker-device",
        help=(
            "List output audio devices, or relay one VRChat instance's "
            "audio to a chosen output device."
        ),
    )
    actions = parser.add_subparsers(dest="speaker_device_action", required=True)

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
    """Emit the device list YAML; map runtime failures to exit 1."""
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
    sys.stdout.write(yaml.safe_dump(payload, sort_keys=False, default_flow_style=False))
    return 0


def _run_route(args: argparse.Namespace) -> int:
    """Open a PID-scoped relay and block until ``Ctrl+C`` or failure."""
    pid: int = args.pid
    device: str | None = args.device
    chunk_seconds: float = args.chunk_seconds
    blocksize: int | None = args.blocksize

    try:
        with route(
            pid,
            device,
            chunk_seconds=chunk_seconds,
            blocksize=blocksize,
        ) as router:
            suffix = " (system default)" if device is None else ""
            print(
                f"route: pid={pid} device={router.device.name!r}{suffix}",
                file=sys.stderr,
            )
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    except KeyboardInterrupt:
        # Ctrl+C raised during Router.__enter__/start before the inner
        # try-block established its own handler — still a clean exit.
        pass
    except (
        DeviceNotFoundError,
        AudioRoutingError,
        VRChatMultipleInstancesError,
        RuntimeError,
        OSError,
        ImportError,
        NotImplementedError,
    ) as exc:
        print(f"vrcpilot: {exc}", file=sys.stderr)
        return 1

    return 0


def run(args: argparse.Namespace) -> int:
    """Dispatch to the requested ``speaker-device`` action."""
    if args.speaker_device_action == "list":
        return _run_list()
    return _run_route(args)
