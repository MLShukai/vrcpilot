"""Linux PipeWire-native speaker backend (per-PID).

Each :class:`PipeWireSpeakerBackend` instance owns two PipeWire
resources keyed by its VRChat ``pid``:

* a ``vrcpilot_tap_{pid}`` ``module-null-sink`` so multiple backends
  never share a capture sink;
* a ``pw-record`` subprocess piping the monitor into a drain thread.

Two-stage explicit global-port-id linking
------------------------------------------

Audio reaches the recorder through two explicit ``pw-link`` hops, each
made by **global PipeWire port id** rather than node / port name:

#. *producer -> tap*: VRChat's ``sink_input`` output ports are linked
   onto the per-pid ``vrcpilot_tap_{pid}`` null-sink's playback ports.
   The stream's existing link to the default sink is left in place —
   the tap is an extra consumer, not a replacement route, so **the user
   keeps hearing VRChat through the default speakers while recording.**
#. *tap monitor -> recorder*: the tap's monitor ports are linked onto a
   ``pw-record`` subprocess spawned with ``--target=0`` (auto-connect
   disabled, so its input ports stay free for us to wire explicitly).

Linking by global port id is the only form that is both deterministic
*and* collision-free. Two concurrent VRChat instances share the node
name ``VRChat.exe``, so a name-based ``pw-link`` would always resolve
the same producer and silently cross-wire the taps; and the node-id
form returns a non-zero exit code even on success, so it cannot drive
returncode branching. Global port ids are unique per port, so each hop
links exactly the intended ports. Port ids are resolved from
``pw-dump`` (the only source that maps a node id to its ports under a
name collision).

The earlier design moved the stream with ``Pulse.sink_input_move``
(``target.object`` metadata via the Pulse-compat layer); Wireplumber's
session policy (``stream-restore`` / ``follow-default-target``) silently
reverted that move after the API call returned success. The same policy
also redirects a name-targeted ``pw-record`` to the default sink monitor
when more than one sink exists — which is why the recorder is spawned
with ``--target=0`` and wired by explicit port id instead. User-created
explicit ``pw-link`` port links are not subject to that policy.

Diagnostic surface
------------------

Linking decisions are observable from the log stream alone. Every
VRChat-like ``sink_input`` is logged at INFO with a pipe-delimited
schema, each ``pw-link`` invocation's outcome is logged with a fixed
prefix (``port link ok`` / ``port link already present`` / ``port link
failed``) keyed by the global port ids, each node-to-node pass ends in
a ``port link summary`` line, the listener emits an ``on_pulse_event``
line per event so a post-mortem can confirm the listener actually
fired, and ``pw-record``'s stderr is forwarded line-by-line. This
contract is what the multi-instance e2e captures rely on for
post-mortem reconstruction.

State / cleanup
---------------

A breadcrumb at
``$XDG_RUNTIME_DIR/vrcpilot/speaker-taps/{vrchat_pid}.json`` records
the module ids plus the VRChat process's ``create_time``. Start-up
idempotently sweeps tap modules whose VRChat PID is dead or has been
recycled (``create_time`` mismatches the breadcrumb), so an ungraceful
previous run never wedges PipeWire. The ``create_time`` check matters
because PIDs are recycled by the kernel; without it, a tap from a
crashed run would be wrongly treated as belonging to whichever new
process happened to inherit the same PID.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError("vrcpilot.speaker.linux is Linux-only")

import atexit
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import warnings
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Final, TypeVar, override

import numpy as np
import psutil
from numpy.typing import NDArray

from vrcpilot.speaker.base import CHANNELS, SpeakerBackend

_logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: External CLIs the backend relies on. Missing any is a hard
#: start-up failure with an actionable error message.
_REQUIRED_CLIS: Final[tuple[str, ...]] = ("pw-record", "pw-link", "pw-dump")

#: Match a ``vrcpilot_tap_<pid>`` null-sink argument. The trailing
#: ``\s`` is load-bearing — see :func:`_extract_tap_pid` for why
#: anchoring on PulseAudio's token separator is required.
_NULL_SINK_RE: Final[re.Pattern[str]] = re.compile(r"sink_name=vrcpilot_tap_(\d+)\s")

#: Drain thread reads this many bytes per syscall. 4 KiB ≈ 10 ms of
#: stereo float32 @ 48 kHz, small enough to keep latency low but large
#: enough not to syscall every sample.
_DRAIN_CHUNK_BYTES: Final[int] = 4096

#: ``pulse.sink_list()`` can take a few ms to reflect a freshly loaded
#: ``module-null-sink``. Spin briefly before giving up.
_SINK_LOOKUP_RETRIES: Final[int] = 10
_SINK_LOOKUP_INTERVAL_SEC: Final[float] = 0.05

#: ``module_load`` can race the PipeWire-Pulse daemon when two backends
#: unload stale modules in quick succession: the daemon may try to
#: reuse a just-freed module index for the new load and return
#: ``Operation canceled`` (-125). Retrying with a short backoff lets the
#: free pool settle without escalating the failure to the caller.
_MODULE_LOAD_RETRIES: Final[int] = 3
_MODULE_LOAD_RETRY_DELAY_SEC: Final[float] = 0.1

#: ``create_time`` tolerance when checking for PID reuse. ``psutil``
#: reports times in seconds; a small slack absorbs filesystem timestamp
#: rounding without letting an honest reuse slip through.
_CREATE_TIME_TOLERANCE_SEC: Final[float] = 0.05


def _tap_sink_name(pid: int) -> str:
    """Return the per-PID null-sink name used for ``pid``'s audio tap."""
    return f"vrcpilot_tap_{pid}"


def _record_node_name(pid: int) -> str:
    """Return the per-PID ``pw-record`` node name.

    A ``pw-record`` node does not expose ``application.process.id`` in
    its PipeWire props, so the recorder cannot be located by OS pid.
    Instead it is spawned with a unique ``node.name`` (this value, via
    ``pw-record -P``) so two concurrent backends never clash: a plain
    ``pw-record`` node name would collide and the capture-side link
    could attach to the wrong recorder.
    """
    return f"vrcpilot_rec_{pid}"


def _null_sink_args(pid: int) -> str:
    """``module-null-sink`` argument string for the ``pid`` tap.

    Mirrors the channel / rate / format the rest of the speaker stack
    assumes (see :mod:`vrcpilot.speaker.base`).
    """
    return (
        f"sink_name={_tap_sink_name(pid)} "
        f"sink_properties=device.description=VRCPilotTap_{pid} "
        "rate=48000 channels=2 format=float32le"
    )


def _pw_record_argv(pid: int) -> tuple[str, ...]:
    """Argv template for the ``pw-record`` subprocess of ``pid``'s tap.

    ``--target=0`` disables auto-connect so the recorder's input ports
    stay free; the backend then links the tap's monitor ports onto them
    by explicit global port id (a name-targeted recorder would be
    redirected to the default sink monitor by the session manager when
    more than one sink exists). ``-P node.name=...`` tags the node with
    a unique per-pid name so the capture-side link can find it without
    colliding with a concurrent backend's recorder. The trailing ``-``
    writes raw PCM to stdout; format / rate / channel count match
    :mod:`vrcpilot.speaker.base` exactly so no resampling is required.
    """
    return (
        "pw-record",
        "--target=0",
        "-P",
        f"node.name={_record_node_name(pid)}",
        "--format=f32",
        "--rate=48000",
        "--channels=2",
        "--latency=20ms",
        "-",
    )


def _extract_tap_pid(module_name: str | None, argument: str | None) -> int | None:
    """Return the VRChat PID encoded in a ``module-null-sink`` argument.

    Returns ``None`` when ``module_name`` / ``argument`` does not belong
    to one of our taps.

    PulseAudio separates argument tokens with whitespace, so the regex
    anchors on a trailing ``\\s`` and a trailing space is appended to
    ``argument`` before matching. Without that anchor,
    ``vrcpilot_tap_1234`` would spuriously match ``vrcpilot_tap_12345``
    and the stale-tap sweep would unload an unrelated, live PID's sink.
    """
    if not module_name or not argument:
        return None
    if module_name != "module-null-sink":
        return None
    needle = argument.strip() + " "
    m = _NULL_SINK_RE.search(needle)
    return int(m.group(1)) if m else None


def _coerce_optional_int(value: Any) -> int | None:
    """Return ``value`` as an ``int`` or ``None`` if it cannot convert.

    PipeWire proplist values arrive as strings (e.g. ``object.serial =
    '9228'``); this normalises them to ``int`` for use as node
    identifiers, dropping anything non-numeric without raising.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    """Return ``value`` if it is a ``str``, else ``None``.

    Narrows a proplist value to ``str`` so the diagnostic / classification
    logic in :meth:`PipeWireSpeakerBackend._resolve_vrchat_node_ids` can
    treat any non-string (or missing) field uniformly as absent.
    """
    return value if isinstance(value, str) else None


def _pw_link_already_linked(stderr: str) -> bool:
    """Whether ``pw-link`` stderr signals an already-existing link.

    The deterministic explicit-port form returns a non-zero exit code
    with ``failed to link ports: File exists`` when the requested port
    pair is already linked. That is the idempotent case (a re-link from
    the event listener, or a stream that was already routed), not a
    failure — see the empirically captured ``pw-link`` behaviour in the
    module's reference notes.

    >>> _pw_link_already_linked("failed to link ports: File exists")
    True
    >>> _pw_link_already_linked("failed to link ports: No such file or directory")
    False
    """
    return "File exists" in stderr


def _parse_pw_dump(raw: bytes) -> list[dict[str, Any]]:
    """Parse ``pw-dump`` output into a list of object dicts.

    ``pw-dump`` emits a JSON array of PipeWire objects. Returns an empty
    list (never raises) when the payload is empty, not valid JSON, or
    not a JSON array — the helpers that consume the dump degrade to "no
    match" rather than aborting start-up, and ``pw-dump`` piped output
    can intermittently be empty under daemon contention.

    Non-dict array elements are dropped so downstream ``info.props``
    access is always against a mapping.
    """
    if not raw:
        return []
    try:
        data: Any = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, list):
        return []
    objects: list[dict[str, Any]] = [
        obj  # pyright: ignore[reportUnknownVariableType]
        for obj in data  # pyright: ignore[reportUnknownVariableType]
        if isinstance(obj, dict)
    ]
    return objects


def _dump_props(obj: dict[str, Any]) -> dict[str, Any]:
    """Return ``obj['info']['props']`` as a dict, or ``{}`` when absent."""
    info_raw: Any = obj.get("info")
    if not isinstance(info_raw, dict):
        return {}
    info: dict[Any, Any] = info_raw  # pyright: ignore[reportUnknownVariableType]
    props_raw: Any = info.get("props")
    if not isinstance(props_raw, dict):
        return {}
    props: dict[Any, Any] = props_raw  # pyright: ignore[reportUnknownVariableType]
    return props


def _find_node_id_by_name(dump: list[dict[str, Any]], node_name: str) -> int | None:
    """Return the global id of the Node whose ``node.name`` matches.

    Scans ``dump`` for a ``PipeWire:Interface:Node`` object whose
    ``info.props['node.name']`` equals ``node_name`` and returns its
    top-level ``id`` (the global object id). Returns ``None`` when no
    such node exists. The first match wins; the backend's tap and
    recorder names are unique per pid, so a collision is not expected.
    """
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = _dump_props(obj)
        if props.get("node.name") == node_name:
            node_id = _coerce_optional_int(obj.get("id"))
            if node_id is not None:
                return node_id
    return None


def _find_ports(
    dump: list[dict[str, Any]], node_id: int, direction: str
) -> dict[str, int]:
    """Return ``{audio.channel: global port id}`` for a node's ports.

    Scans ``dump`` for ``PipeWire:Interface:Port`` objects owned by
    ``node_id`` (``info.props['node.id']``) in the given ``direction``
    (``'in'`` or ``'out'``) and maps each port's ``audio.channel`` (e.g.
    ``'FL'`` / ``'FR'``) to its top-level global ``id``. Ports without a
    usable channel or global id are skipped.

    Filtering by direction matters: a ``pw-record`` node carries both
    ``input_<CH>`` (in) and ``monitor_<CH>`` (out) ports, and a null
    sink carries both ``playback_<CH>`` (in) and ``monitor_<CH>`` (out)
    ports, so only the direction-matched set is returned.
    """
    ports: dict[str, int] = {}
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Port":
            continue
        props = _dump_props(obj)
        if _coerce_optional_int(props.get("node.id")) != node_id:
            continue
        if props.get("port.direction") != direction:
            continue
        channel_raw: Any = props.get("audio.channel")
        if not isinstance(channel_raw, str):
            continue
        port_id = _coerce_optional_int(obj.get("id"))
        if port_id is None:
            continue
        ports[channel_raw] = port_id
    return ports


def _poll_for(probe: Callable[[], _T | None]) -> _T | None:
    """Call ``probe`` until it returns non-``None`` or the budget runs out.

    Shared readiness-gate loop for both PipeWire resources that take a few
    ms to register after they are requested: the tap ``module-null-sink``
    (visible by name in ``sink_list``) and the ``pw-record`` node (visible
    by name in ``pw-dump``). Spins :data:`_SINK_LOOKUP_RETRIES` times with
    a :data:`_SINK_LOOKUP_INTERVAL_SEC` sleep between attempts and returns
    the first non-``None`` probe result, or ``None`` if it never appeared
    within the budget.
    """
    for _ in range(_SINK_LOOKUP_RETRIES):
        result = probe()
        if result is not None:
            return result
        time.sleep(_SINK_LOOKUP_INTERVAL_SEC)
    return None


class PipeWireSpeakerBackend(SpeakerBackend):
    """SpeakerBackend that captures one VRChat process via native PipeWire.

    The constructor performs the full per-pid setup under an
    ``ExitStack`` so a partial start-up never leaks a null-sink or the
    ``pw-record`` subprocess. :meth:`close` is also registered with
    :func:`atexit` so an interpreter shutdown that bypasses
    ``__exit__`` still releases PipeWire resources.

    Args:
        read_timeout: Seconds :meth:`read` waits for the first chunk
            before returning an empty array. Must be ``> 0``.
        pid: Target VRChat PID. A dedicated ``vrcpilot_tap_{pid}``
            null-sink is created and only that process's sink_inputs
            are linked onto it, so concurrent VRChat instances stay
            isolated. Callers (typically
            :class:`vrcpilot.speaker.Speaker`) pre-resolve the PID
            rather than re-resolving here, so the backend's lifetime
            stays bound to one definite VRChat process.

    Raises:
        ValueError: ``read_timeout`` is not strictly positive.
        RuntimeError: The required CLI is missing, or the PulseAudio /
            PipeWire control plane refused the null-sink load.
    """

    _read_timeout: float
    _pid: int
    _pulse: Any
    _null_sink_module_id: int | None
    _state_file: Path | None
    _record_proc: Any
    _drain_thread: threading.Thread | None
    _drain_err_thread: threading.Thread | None
    _event_thread: threading.Thread | None
    _stop_drain: threading.Event
    _stop_events: threading.Event
    _stdout_lock: threading.Lock
    _stdout_condition: threading.Condition
    _buffer: bytearray
    _stdout_exception: BaseException | None
    _closed: bool
    _lock: threading.Lock

    def __init__(self, *, read_timeout: float = 2.0, pid: int) -> None:
        if read_timeout <= 0:
            raise ValueError(f"read_timeout must be > 0 (got {read_timeout})")

        missing = [c for c in _REQUIRED_CLIS if shutil.which(c) is None]
        if missing:
            raise RuntimeError(
                f"PipeWire backend requires {_REQUIRED_CLIS}; missing: "
                f"{missing}. Install 'pipewire' and 'pipewire-pulse' "
                "(or distro equivalents)."
            )

        self._read_timeout = read_timeout
        self._pid = pid
        self._closed = False
        self._lock = threading.Lock()
        self._null_sink_module_id = None
        self._state_file = None
        self._record_proc = None
        self._drain_thread = None
        self._drain_err_thread = None
        self._event_thread = None
        self._stop_drain = threading.Event()
        self._stop_events = threading.Event()
        self._stdout_lock = threading.Lock()
        self._stdout_condition = threading.Condition(self._stdout_lock)
        self._buffer = bytearray()
        self._stdout_exception = None

        # Unwinds on failure: every successful step pushes a rollback
        # callback so a partial start-up never leaks a null-sink or a
        # pw-record subprocess.
        stack = ExitStack()
        try:
            # Client name is suffixed with the VRChat PID so the daemon
            # log identifies which backend each ``client ... [vrcpilot-tap-N]``
            # message belongs to. Without the suffix two concurrent
            # backends would both register as plain ``vrcpilot-tap`` and
            # post-mortems could not tell their LOAD_MODULE / unload
            # ordering apart.
            self._pulse = self._open_pulse(f"vrcpilot-tap-{self._pid}")
            stack.callback(self._safe_close_pulse)

            self._reset_stale_taps()

            self._null_sink_module_id = self._load_null_sink()
            stack.callback(self._safe_unload_null_sink)

            self._state_file = self._write_state_file()
            stack.callback(self._safe_remove_state_file)

            # The tap's playback ports must be daemon-visible before the
            # producer / capture links resolve them; gate on the sink
            # appearing. A miss is logged and tolerated (the links below
            # then no-op against an absent tap and read() surfaces empty
            # audio rather than crashing start-up).
            if not self._wait_for_tap_ready():
                _logger.warning(
                    "tap sink not yet visible at start-up | self_pid=%d",
                    self._pid,
                )

            # Spawn the recorder first (with auto-connect disabled) so its
            # free input ports exist for the capture-side link.
            self._record_proc = self._spawn_pw_record()
            stack.callback(self._safe_terminate_record_proc)

            # LIFO ordering: the stderr drain is registered BEFORE the
            # stdout drain so it is joined AFTER stdout during teardown.
            # pw-record closes its stderr only after its stdout, so we
            # mirror that natural order.
            self._drain_err_thread = threading.Thread(
                target=self._drain_stderr,
                name="PipeWireSpeakerDrainErr",
                daemon=True,
            )
            self._drain_err_thread.start()
            stack.callback(self._safe_join_drain_err_thread)

            self._drain_thread = threading.Thread(
                target=self._drain_stdout,
                name="PipeWireSpeakerDrain",
                daemon=True,
            )
            self._drain_thread.start()
            stack.callback(self._safe_join_drain_thread)

            # Capture side: wait for the recorder's node/ports to register,
            # then link the tap monitor onto them. Then wire the producer
            # side (VRChat sink_inputs -> tap). A missing recorder node is
            # logged and tolerated; links garbage-collect with the tap.
            if self._wait_for_record_node() is None:
                _logger.warning(
                    "pw-record node not visible, skipping capture link | self_pid=%d",
                    self._pid,
                )
            else:
                self._link_tap_monitor_to_record()

            self._link_existing_vrchat_nodes_to_tap()

            self._event_thread = threading.Thread(
                target=self._listen_events,
                name="PipeWireSpeakerEvents",
                daemon=True,
            )
            self._event_thread.start()
            stack.callback(self._safe_join_event_thread)
        except BaseException:
            stack.close()
            raise

        # All resources held — commit the stack so we keep them.
        stack.pop_all()
        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Test seams (substituted in unit tests via ``mocker.patch.object``)
    # ------------------------------------------------------------------

    def _open_pulse(self, client_name: str) -> Any:
        """Construct the ``pulsectl.Pulse`` control connection.

        Carved out as its own method so tests can substitute a stand-in
        via ``mocker.patch.object`` without mocking ``pulsectl`` (which
        the project's testing policy forbids for 3rd-party surfaces).
        The ``pulsectl`` import is kept local so non-Linux test runs
        never need the package available.
        """
        from pulsectl import (  # pyright: ignore[reportMissingTypeStubs]
            Pulse,
        )

        return Pulse(client_name)  # pyright: ignore[reportUnknownVariableType]

    def _spawn_pw_record(self) -> Any:
        """Spawn the ``pw-record`` subprocess piped to stdout.

        Same test-seam role as :meth:`_open_pulse`: an isolated factory
        so tests can replace it with a fake :class:`subprocess.Popen`
        without monkey-patching :mod:`subprocess` itself.

        ``bufsize=0`` keeps the OS pipe un-double-buffered so the
        drain thread sees bytes at PipeWire's emission cadence rather
        than after a userland buffer fills.
        """
        return subprocess.Popen(
            list(_pw_record_argv(self._pid)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def _pw_link_run_raw(self, args: list[str]) -> subprocess.CompletedProcess[bytes]:
        """Run ``pw-link`` once and return the completed process.

        The single subprocess surface through which the backend touches
        ``pw-link``. Same test-seam role as :meth:`_open_pulse` /
        :meth:`_spawn_pw_record` / :meth:`_module_load_raw`: tests
        substitute the per-call outcome via
        ``mocker.patch.object(backend, '_pw_link_run_raw',
        side_effect=[...])`` without monkey-patching :mod:`subprocess`
        itself (which the project's testing policy forbids for 3rd-party
        surfaces).

        ``check=False`` so callers can branch on ``returncode`` /
        ``stderr`` — an already-present link is a non-zero,
        non-exceptional outcome.
        """
        return subprocess.run(
            ["pw-link", *args],
            capture_output=True,
            check=False,
        )

    def _pw_dump_raw(self) -> bytes:
        """Run ``pw-dump`` and return its raw stdout bytes.

        The single subprocess surface through which the backend touches
        ``pw-dump``; same test-seam role as :meth:`_open_pulse` /
        :meth:`_spawn_pw_record` / :meth:`_pw_link_run_raw`.

        ``pw-dump`` is written to a temporary file and read back rather
        than captured straight from the pipe: piping ``pw-dump`` output
        directly is racy under daemon contention (it intermittently
        returns an empty or truncated payload), whereas redirecting to a
        file yields the complete dump. The temp file is always removed.
        """
        with tempfile.NamedTemporaryFile(
            prefix="vrcpilot-pw-dump-", suffix=".json", delete=False
        ) as handle:
            dump_path = handle.name
        try:
            with open(dump_path, "wb") as out:
                subprocess.run(["pw-dump"], stdout=out, check=False)
            return Path(dump_path).read_bytes()
        finally:
            try:
                os.unlink(dump_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Start-up helpers
    # ------------------------------------------------------------------

    def _reset_stale_taps(self) -> None:
        """Unload leftover vrcpilot ``module-null-sink``s from prior runs.

        Decodes the VRChat PID from each argument. Unloads when:

        * the PID equals ``self._pid`` (prior-crash residue of our own
          slot), or
        * the PID does not exist anymore, or
        * the PID exists but the recorded ``create_time`` in our state
          file does not match (PID reuse).

        Leaves PIDs that look live and have a matching state file alone
        so a concurrently-running backend is never disturbed.
        """
        try:
            modules: list[Any] = self._pulse.module_list()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("module_list failed during stale reset: %s", exc)
            return

        null_sinks: list[tuple[int, int]] = []
        for module in modules:
            name = _optional_str(getattr(module, "name", None))
            arg = _optional_str(getattr(module, "argument", None))
            pid = _extract_tap_pid(name, arg)
            if pid is None:
                continue
            index_raw: Any = getattr(module, "index", None)
            if not isinstance(index_raw, int):
                continue
            null_sinks.append((index_raw, pid))

        for index, pid in null_sinks:
            if self._tap_is_stale(pid):
                self._unload_module_safely(index, "module-null-sink", pid)

    def _tap_is_stale(self, pid: int) -> bool:
        """Whether the tap module for ``pid`` is safe to unload."""
        if pid == self._pid:
            return True
        if not psutil.pid_exists(pid):
            return True
        state = self._read_state_file_for(pid)
        if state is None:
            # Live PID with no breadcrumb — could be a concurrent
            # backend whose state file is still being written. Don't
            # touch it; the worst case is one extra startup-time noop.
            return False
        recorded_raw: Any = state.get("vrchat_create_time")
        if not isinstance(recorded_raw, (int, float)):
            return False
        try:
            current_ct = psutil.Process(pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return True
        return abs(current_ct - float(recorded_raw)) > _CREATE_TIME_TOLERANCE_SEC

    def _unload_module_safely(self, index: int, module_name: str, pid: int) -> None:
        """Best-effort ``module_unload`` for a known-stale tap module."""
        try:
            self._pulse.module_unload(index)  # pyright: ignore[reportUnknownMemberType]
            _logger.info(
                "unloaded stale %s (vrchat pid=%d, module=%d)",
                module_name,
                pid,
                index,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "failed to unload stale %s index=%d pid=%d: %s",
                module_name,
                index,
                pid,
                exc,
            )

    def _module_load_raw(self, module_name: str, args: str) -> Any:
        """Thin wrapper around ``pulse.module_load`` carved out as a test seam.

        Same role as :meth:`_open_pulse` / :meth:`_spawn_pw_record`: a
        single-call factory so tests can substitute the per-attempt
        outcome via ``mocker.patch.object(backend, '_module_load_raw',
        side_effect=[...])`` without monkey-patching ``pulsectl`` itself
        (which the project's testing policy forbids for 3rd-party
        surfaces).
        """
        return self._pulse.module_load(module_name, args)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]

    def _load_module(self, module_name: str, args: str, kind_label: str) -> int:
        """``pulse.module_load`` with retry-with-backoff + int validation.

        PipeWire-Pulse occasionally returns ``Operation canceled``
        (-125) when two backends unload stale modules and immediately
        request a new load: the daemon races to reuse the just-freed
        module index. A short retry with a fixed backoff is enough to
        let the free pool settle before re-attempting.
        """
        last_exc: BaseException | None = None
        for attempt in range(1, _MODULE_LOAD_RETRIES + 1):
            try:
                idx: Any = self._module_load_raw(module_name, args)
            except Exception as exc:
                # Broad catch is deliberate: pulsectl's ``PulseError`` is
                # off-limits per the project's 3rd-party surface policy,
                # and PipeWire-Pulse surfaces generic errors here
                # (e.g. ``Operation canceled``) without a stable type.
                last_exc = exc
                _logger.warning(
                    "module_load attempt %d/%d failed | module=%s | error=%s",
                    attempt,
                    _MODULE_LOAD_RETRIES,
                    module_name,
                    exc,
                )
                if attempt < _MODULE_LOAD_RETRIES:
                    time.sleep(_MODULE_LOAD_RETRY_DELAY_SEC)
                continue
            if not isinstance(idx, int):
                raise RuntimeError(
                    f"module_load({kind_label}) returned non-int module id: "
                    f"{type(idx).__name__}"
                )
            if attempt > 1:
                _logger.info(
                    "module_load retry succeeded | module=%s | attempt=%d | "
                    "total_attempts=%d",
                    module_name,
                    attempt,
                    _MODULE_LOAD_RETRIES,
                )
            return idx
        assert last_exc is not None  # loop exited via final-attempt failure
        raise last_exc

    def _load_null_sink(self) -> int:
        """Load the per-pid ``module-null-sink`` and return its index."""
        return self._load_module(
            "module-null-sink", _null_sink_args(self._pid), "null-sink"
        )

    def _resolve_state_dir(self) -> Path:
        """Return (and create) the directory state files live in.

        ``$XDG_RUNTIME_DIR/vrcpilot/speaker-taps`` when the env var is
        set, otherwise ``/tmp/vrcpilot-{uid}/speaker-taps`` so the
        backend still has a stable path on minimal systems where the
        runtime dir is missing.
        """
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime:
            base = Path(runtime) / "vrcpilot" / "speaker-taps"
        else:
            uid = os.getuid() if hasattr(os, "getuid") else 0
            base = Path(f"/tmp/vrcpilot-{uid}") / "speaker-taps"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _state_file_path_for(self, vrchat_pid: int) -> Path:
        """Per-pid state file path.

        May raise ``OSError`` from mkdir.
        """
        return self._resolve_state_dir() / f"{vrchat_pid}.json"

    def _read_state_file_for(self, vrchat_pid: int) -> dict[str, Any] | None:
        """Return the parsed state file dict for ``vrchat_pid`` or ``None``."""
        try:
            path = self._state_file_path_for(vrchat_pid)
        except OSError:
            return None
        if not path.exists():
            return None
        try:
            data: Any = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        result: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
        return result

    def _write_state_file(self) -> Path | None:
        """Persist tap metadata so an external janitor can recover.

        Best-effort: write failures degrade to ``None`` with a warning.
        Normal shutdown still releases the modules via :meth:`close`;
        the file only matters when the process dies ungracefully.
        """
        try:
            path = self._state_file_path_for(self._pid)
        except OSError as exc:
            warnings.warn(f"state dir create failed: {exc}", stacklevel=2)
            return None

        vrchat_ct: float | None
        try:
            vrchat_ct = psutil.Process(self._pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            vrchat_ct = None
        try:
            own_ct = psutil.Process(os.getpid()).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            own_ct = 0.0

        payload: dict[str, Any] = {
            "owner_pid": os.getpid(),
            "owner_create_time": own_ct,
            "null_sink_module_id": self._null_sink_module_id,
            "sink_name": _tap_sink_name(self._pid),
            "vrchat_pid": self._pid,
            "vrchat_create_time": vrchat_ct,
        }
        try:
            path.write_text(json.dumps(payload))
            return path
        except OSError as exc:
            warnings.warn(f"state file write failed: {exc}", stacklevel=2)
            return None

    def _wait_for_tap_ready(self) -> bool:
        """Spin until the per-pid tap sink is visible by name, or give up.

        PipeWire-Pulse can take a few ms to expose a freshly-loaded
        ``module-null-sink`` in ``sink_list()`` (and, equivalently, to
        expose its ``playback_<CH>`` ports to ``pw-link``). Both the
        ``pw-link`` linking and the ``pw-record`` capture target the
        tap *by name*, so the daemon must have published the sink before
        either is invoked. Spin a few times before giving up rather than
        racing the daemon.

        Returns ``True`` once the tap is visible, ``False`` if it never
        appeared within the retry budget (the caller logs and degrades
        rather than aborting start-up — ``pw-record``'s own stderr drain
        surfaces a missing target).
        """
        target = _tap_sink_name(self._pid)

        def probe() -> bool | None:
            sinks: list[Any]
            try:
                sinks = self._pulse.sink_list()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
            except Exception as exc:  # noqa: BLE001
                _logger.warning("sink_list failed: %s", exc)
                return None
            for sink in sinks:
                if getattr(sink, "name", None) == target:
                    return True
            return None

        return _poll_for(probe) is not None

    def _resolve_vrchat_node_ids(self) -> list[int]:
        """Return PipeWire node identifiers for VRChat streams of
        ``self._pid``.

        Each VRChat ``sink_input`` carries its PipeWire node identity in
        its proplist. ``object.id`` is the PipeWire node's global id and
        is the returned identifier — it equals the ``pw-dump`` Node's
        top-level ``id`` and its Ports' ``node.id``, so it keys the
        ``pw-dump`` port lookup in
        :meth:`_link_existing_vrchat_nodes_to_tap`. ``object.serial`` is
        a *different* value (it does not map to ``pw-dump`` node ids) and
        is recorded only as a diagnostic field.

        Filter precedence:

        1. ``proplist['application.process.id']`` exact PID match.
        2. Proton/Wine fallback when ``process.id`` is absent: looks for
           ``application.process.binary == 'VRChat.exe'`` or
           ``'VRChat'`` substring in ``application.name`` /
           ``media.name``. Conservative: if multiple ambiguous streams
           exist alongside any PID-matched stream the ambiguous ones
           are dropped to avoid linking audio that might belong to a
           different VRChat instance.

        Diagnostic contract: every VRChat-like candidate emits one
        ``sink_input candidate | ...`` INFO line (now carrying
        ``node_serial`` / ``node_object_id`` / ``node_name``) and the
        call ends with a single ``sink_input scan summary | ...`` line.
        Tests and the multi-instance e2e captures depend on those
        prefixes existing so a post-mortem can reconstruct which streams
        the linking layer saw and how each was classified — change the
        prefix or schema only with the diagnostic consumers in mind.
        """
        try:
            inputs: list[Any] = self._pulse.sink_input_list()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("sink_input_list failed: %s", exc)
            return []

        matched: list[int] = []
        ambiguous: list[int] = []
        total_candidates = 0
        for inp in inputs:
            proplist_raw: Any = getattr(inp, "proplist", None)
            if not isinstance(proplist_raw, dict):
                continue
            proplist: dict[Any, Any] = proplist_raw  # pyright: ignore[reportUnknownVariableType]
            index_raw: Any = getattr(inp, "index", None)
            if not isinstance(index_raw, int):
                continue

            proc_id_raw: Any = proplist.get("application.process.id")
            proc_id = _coerce_optional_int(proc_id_raw)

            binary = _optional_str(proplist.get("application.process.binary"))
            app_name = _optional_str(proplist.get("application.name"))
            host = _optional_str(proplist.get("application.process.host"))
            media_name = _optional_str(proplist.get("media.name"))

            node_serial = _coerce_optional_int(proplist.get("object.serial"))
            node_object_id = _coerce_optional_int(proplist.get("object.id"))
            node_name = _optional_str(proplist.get("node.name"))

            looks_like_vrchat = (
                binary == "VRChat.exe"
                or (app_name is not None and "VRChat" in app_name)
                or (media_name is not None and "VRChat" in media_name)
            )

            # ``object.id`` IS the PipeWire node global id (it equals the
            # pw-dump Node ``id`` / Port ``node.id``), so it is the
            # identifier used for the port lookup. ``object.serial`` is a
            # different value that does not map to pw-dump node ids and is
            # only logged for diagnostics.
            node_id = node_object_id

            classification: str
            if proc_id is not None and proc_id == self._pid:
                if node_id is not None:
                    matched.append(node_id)
                    classification = "matched"
                else:
                    classification = "matched-no-node-identifier"
            elif proc_id is None and looks_like_vrchat:
                if node_id is not None:
                    ambiguous.append(node_id)
                    classification = "ambiguous"
                else:
                    classification = "ambiguous-no-node-identifier"
            elif looks_like_vrchat:
                # VRChat-like but ``process.id`` rules it out (belongs
                # to a different VRChat PID).
                classification = "skipped-no-vrchat-marker"
            else:
                # Not VRChat at all — skip without logging to keep the
                # diagnostic stream focused.
                continue

            total_candidates += 1
            _logger.info(
                "sink_input candidate | sink_input_index=%d | "
                "process_id_raw=%r | process_id_int=%s | binary=%s | "
                "app_name=%s | host=%s | media_name=%s | "
                "node_serial=%s | node_object_id=%s | node_name=%s | "
                "self_pid=%d | classification=%s",
                index_raw,
                proc_id_raw,
                proc_id,
                binary,
                app_name,
                host,
                media_name,
                node_serial,
                node_object_id,
                node_name,
                self._pid,
                classification,
            )

        _logger.info(
            "sink_input scan summary | self_pid=%d | matched=%s | "
            "ambiguous=%s | total_candidates=%d",
            self._pid,
            matched,
            ambiguous,
            total_candidates,
        )

        if not ambiguous:
            return matched

        # PID-anchored matches keep precedence. The lone-ambiguous,
        # zero-matched case is the only situation we can disambiguate
        # against ``self._pid`` -- everything else is dropped so a
        # multi-instance setup never accidentally captures the wrong
        # VRChat.
        if len(ambiguous) == 1 and not matched:
            return ambiguous

        _logger.warning(
            "%d VRChat-like sink_inputs lack application.process.id; "
            "cannot disambiguate against pid=%d. Skipping ambiguous "
            "inputs to avoid mis-linked audio.",
            len(ambiguous),
            self._pid,
        )
        return matched

    def _wait_for_record_node(self) -> int | None:
        """Spin until the ``pw-record`` node appears in ``pw-dump``.

        ``_spawn_pw_record`` returns as soon as the subprocess is forked,
        but the recorder's PipeWire node (and its free input ports) take
        a few ms to register with the daemon. The capture-side link
        cannot resolve those ports until then, so poll ``pw-dump`` for
        the node named :func:`_record_node_name` and return its global
        id.

        Returns the node id once visible, or ``None`` if it never
        appeared within the retry budget (the caller logs and degrades;
        ``read`` will then surface empty audio rather than crashing).
        """
        target = _record_node_name(self._pid)

        def probe() -> int | None:
            dump = _parse_pw_dump(self._pw_dump_raw())
            return _find_node_id_by_name(dump, target)

        return _poll_for(probe)

    def _pw_link_ports(self, out_port_id: int, in_port_id: int) -> None:
        """Link one output port to one input port by global port id.

        The deterministic, collision-free ``pw-link`` form: both sides
        are global PipeWire port ids, so exactly the intended ports are
        connected (a name-based link cross-wires under the shared
        ``VRChat.exe`` node name; a node-id link returns non-zero even on
        success). Outcome is branched off the returncode:

        * returncode 0 → INFO ``port link ok``;
        * non-zero whose stderr signals an existing link (``File
          exists``) → INFO ``port link already present`` (idempotent
          re-link, e.g. from the event listener);
        * any other non-zero → WARNING ``port link failed`` with the
          returncode.

        The ``pw-link`` stderr is forwarded line-by-line at INFO under
        ``pw-link stderr | ...`` regardless of returncode.
        """
        try:
            result = self._pw_link_run_raw([str(out_port_id), str(in_port_id)])
        except Exception as exc:  # noqa: BLE001
            # ``pw-link`` is on PATH (checked at start-up); an exception
            # here is a process-spawn failure, not a link rejection.
            _logger.warning(
                "port link failed | out_port=%d | in_port=%d | "
                "returncode=%d | self_pid=%d",
                out_port_id,
                in_port_id,
                -1,
                self._pid,
            )
            _logger.warning(
                "pw-link spawn failed | out_port=%d | in_port=%d | error=%s",
                out_port_id,
                in_port_id,
                exc,
            )
            return

        stderr_text = result.stderr.decode("utf-8", errors="replace")
        for line in stderr_text.splitlines():
            stripped = line.rstrip()
            if stripped:
                _logger.info("pw-link stderr | %s", stripped)

        if result.returncode == 0:
            _logger.info(
                "port link ok | out_port=%d | in_port=%d | self_pid=%d",
                out_port_id,
                in_port_id,
                self._pid,
            )
        elif _pw_link_already_linked(stderr_text):
            _logger.info(
                "port link already present | out_port=%d | in_port=%d | self_pid=%d",
                out_port_id,
                in_port_id,
                self._pid,
            )
        else:
            _logger.warning(
                "port link failed | out_port=%d | in_port=%d | "
                "returncode=%d | self_pid=%d",
                out_port_id,
                in_port_id,
                result.returncode,
                self._pid,
            )

    def _link_ports_between_nodes(
        self,
        dump: list[dict[str, Any]],
        src_node_id: int,
        src_direction: str,
        dst_node_id: int,
        dst_direction: str,
    ) -> int:
        """Link every shared channel between two nodes by global port id.

        Resolves both nodes' port maps from ``dump`` (source ports in
        ``src_direction``, destination ports in ``dst_direction``) and
        links each channel present on both sides via
        :meth:`_pw_link_ports`. Returns the number of channels linked.

        Ends with one ``port link summary`` INFO line so a post-mortem
        can see how many channels were wired between the two nodes
        without parsing every per-port line.
        """
        src_ports = _find_ports(dump, src_node_id, src_direction)
        dst_ports = _find_ports(dump, dst_node_id, dst_direction)
        channels = 0
        for channel, out_port in src_ports.items():
            in_port = dst_ports.get(channel)
            if in_port is None:
                continue
            self._pw_link_ports(out_port, in_port)
            channels += 1
        _logger.info(
            "port link summary | src_node=%d | dst_node=%d | channels=%d | self_pid=%d",
            src_node_id,
            dst_node_id,
            channels,
            self._pid,
        )
        return channels

    def _link_existing_vrchat_nodes_to_tap(self) -> None:
        """Link every resolved VRChat node's output ports onto the tap.

        Producer side of the chain: snapshots ``pw-dump`` once, resolves
        the tap node id by name, and for each VRChat node id (from
        :meth:`_resolve_vrchat_node_ids`) links its output ports onto the
        tap's playback ports by global port id.

        No link is ever explicitly torn down: when either the VRChat
        node or the tap ``module-null-sink`` is destroyed, PipeWire
        garbage-collects the dangling link. :meth:`close` unloads the
        null-sink, which removes the tap's ports and so reaps every link
        this method created.

        Idempotent (re-runnable from the event listener): an
        already-linked channel re-reports ``port link already present``
        without side effects.
        """
        node_ids = self._resolve_vrchat_node_ids()
        if not node_ids:
            return
        dump = _parse_pw_dump(self._pw_dump_raw())
        tap_node_id = _find_node_id_by_name(dump, _tap_sink_name(self._pid))
        if tap_node_id is None:
            _logger.warning(
                "tap node not found in pw-dump, skipping producer links | self_pid=%d",
                self._pid,
            )
            return
        for node_id in node_ids:
            self._link_ports_between_nodes(dump, node_id, "out", tap_node_id, "in")

    def _link_tap_monitor_to_record(self) -> None:
        """Link the tap's monitor ports onto the ``pw-record`` input ports.

        Capture side of the chain: snapshots ``pw-dump`` once, resolves
        the tap node (by name) and the recorder node (by its unique
        ``node.name``, since ``pw-record`` does not expose a process id),
        then links the tap's monitor ports onto the recorder's input
        ports by global port id. Without this the ``--target=0`` recorder
        stays unconnected and captures silence.
        """
        dump = _parse_pw_dump(self._pw_dump_raw())
        tap_node_id = _find_node_id_by_name(dump, _tap_sink_name(self._pid))
        record_node_id = _find_node_id_by_name(dump, _record_node_name(self._pid))
        if tap_node_id is None or record_node_id is None:
            _logger.warning(
                "capture-side nodes not found in pw-dump | tap_found=%s | "
                "record_found=%s | self_pid=%d",
                tap_node_id is not None,
                record_node_id is not None,
                self._pid,
            )
            return
        self._link_ports_between_nodes(dump, tap_node_id, "out", record_node_id, "in")

    # ------------------------------------------------------------------
    # Data plane
    # ------------------------------------------------------------------

    def _drain_stdout(self) -> None:
        """Drain ``pw-record`` stdout into the shared buffer.

        Background-thread body. Exits on EOF, on read error, or when
        :attr:`_stop_drain` is set. Errors are stashed in
        :attr:`_stdout_exception` and raised from the next :meth:`read`
        so a dead thread never goes unnoticed by the consumer.
        """
        stdout = self._record_proc.stdout
        if stdout is None:
            with self._stdout_condition:
                self._stdout_exception = RuntimeError(
                    "pw-record subprocess has no stdout pipe"
                )
                self._stdout_condition.notify_all()
            return
        try:
            while not self._stop_drain.is_set():
                chunk = stdout.read(_DRAIN_CHUNK_BYTES)
                if not chunk:
                    break
                with self._stdout_condition:
                    self._buffer.extend(chunk)
                    self._stdout_condition.notify_all()
        except Exception as exc:  # noqa: BLE001
            with self._stdout_condition:
                self._stdout_exception = exc
                self._stdout_condition.notify_all()

    def _drain_stderr(self) -> None:
        """Drain ``pw-record`` stderr line-by-line into :data:`_logger`.

        Background-thread body. Exits on EOF / read error.

        The recorder is spawned with ``--target=0`` and wired by
        explicit port id, so it never auto-connects to the wrong node;
        but it can still emit ALSA / PipeWire connection errors and xrun
        warnings, and the only signal of those is a stderr line. Every
        line is forwarded at INFO under the ``pw-record stderr | ...``
        prefix so they show up in the same log stream as the linking
        diagnostics rather than being lost to the subprocess's own
        stream.

        Errors reading stderr are logged but never escalated — losing
        the diagnostic stream must not take down the data plane.
        """
        stderr = self._record_proc.stderr
        if stderr is None:
            return
        try:
            while True:
                line = stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                _logger.info("pw-record stderr | %s", decoded)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("pw-record stderr drain failed: %s", exc)

    @override
    def read(self) -> NDArray[np.float32]:
        with self._lock:
            if self._closed:
                raise RuntimeError("PipeWireSpeakerBackend is closed")

        # Block up to read_timeout for the first byte, then swap out the
        # whole buffer in one shot so a single read hand-off covers every
        # sample buffered since the previous call. Drain-thread errors
        # are checked both before and after the wait so an exception
        # planted concurrently with the wait is never silently dropped
        # (the producer-side notify could race an unguarded pre-wait
        # check).
        with self._stdout_condition:
            exc = self._stdout_exception
            if exc is None and not self._buffer:
                self._stdout_condition.wait(timeout=self._read_timeout)
                exc = self._stdout_exception
            if exc is not None:
                self._stdout_exception = None
                raise RuntimeError(f"pw-record drain thread failed: {exc}") from exc
            chunk = bytes(self._buffer)
            self._buffer.clear()

        if not chunk:
            return np.zeros((0, CHANNELS), dtype=np.float32)

        flat = np.frombuffer(chunk, dtype=np.float32)
        remainder = flat.size % CHANNELS
        if remainder:
            _logger.warning(
                "pw-record returned %d float32 samples not divisible by "
                "%d channels; dropping %d trailing samples.",
                flat.size,
                CHANNELS,
                remainder,
            )
            flat = flat[: flat.size - remainder]
        return flat.reshape(-1, CHANNELS).copy()

    # ------------------------------------------------------------------
    # Event listener
    # ------------------------------------------------------------------

    def _listen_events(self) -> None:
        """Drive ``pulse.event_listen`` for ``sink_input`` events.

        Background-thread body. Loops inside ``event_listen`` until the
        callback (or :meth:`close`) flips ``event_listener_running`` to
        ``False``. Errors are logged but never propagated — a dead
        event listener must not take down the data plane.
        """
        try:
            self._pulse.event_mask_set("sink_input")  # pyright: ignore[reportUnknownMemberType]
            self._pulse.event_callback_set(self._on_pulse_event)  # pyright: ignore[reportUnknownMemberType]
            self._pulse.event_listen()  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("pulse event listener exited: %s", exc)

    def _on_pulse_event(self, event: Any) -> None:
        """Link freshly-created VRChat ``sink_input``s onto the tap.

        Without this callback, a new sink_input that VRChat creates
        mid-session (e.g. when the user opens a UI dialog with its own
        audio stream, or a world reload re-plugs the stream) would only
        be linked to the default sink and bypass the capture entirely.
        Re-linking is idempotent (already-present ports re-report
        ``link already present``).

        Pulsectl callback. Every event emits one ``on_pulse_event |
        ...`` INFO line so a post-mortem can confirm the listener
        actually fired (the data plane being silent while the listener
        never woke up is a distinct failure mode). Failures are logged
        but swallowed — the listener must keep running. Honours
        :attr:`_stop_events` as the exit signal back into
        :meth:`_listen_events`.
        """
        if self._stop_events.is_set():
            try:
                self._pulse.event_listener_running = False  # pyright: ignore[reportAttributeAccessIssue]
            except Exception as exc:  # noqa: BLE001
                _logger.warning("event_listener_running write failed: %s", exc)
            return
        facility = getattr(event, "facility", None)
        event_type = getattr(event, "t", None)
        _logger.info(
            "on_pulse_event | facility=%s | type=%s | self_pid=%d",
            facility,
            event_type,
            self._pid,
        )
        if facility != "sink_input" or event_type != "new":
            return
        try:
            self._link_existing_vrchat_nodes_to_tap()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("auto-link failed for event %s: %s", event, exc)

    # ------------------------------------------------------------------
    # Teardown helpers — each one logs failures and returns normally so
    # the ExitStack / close() chain can continue.
    # ------------------------------------------------------------------

    def _safe_close_pulse(self) -> None:
        if self._pulse is None:
            return
        try:
            self._pulse.close()  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"pulse close failed: {exc}", stacklevel=2)

    def _safe_unload_null_sink(self) -> None:
        """Unload the per-pid null-sink module, swallowing teardown errors.

        Kept as a named method (rather than inlined into the
        ``ExitStack.callback`` registration / :meth:`close`) because
        ``ExitStack.callback`` and tracebacks render the callable's
        ``__name__``: a frame labelled ``_safe_unload_null_sink`` is
        far more debuggable from a partial-teardown log than a generic
        anonymous callable.
        """
        if self._null_sink_module_id is None or self._pulse is None:
            return
        try:
            self._pulse.module_unload(self._null_sink_module_id)  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"module-null-sink unload failed: {exc}", stacklevel=2)
        self._null_sink_module_id = None

    def _safe_remove_state_file(self) -> None:
        if self._state_file is None:
            return
        try:
            self._state_file.unlink(missing_ok=True)
        except OSError as exc:
            warnings.warn(f"state file unlink failed: {exc}", stacklevel=2)
        self._state_file = None

    def _safe_terminate_record_proc(self) -> None:
        if self._record_proc is None:
            return
        # ``_stop_drain`` is owned by ``_safe_join_drain_thread``;
        # terminate itself causes pw-record to close its stdout and
        # unblock the drain loop, which is the only signal that
        # actually wakes ``stdout.read``.
        try:
            self._record_proc.terminate()
            try:
                self._record_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                try:
                    self._record_proc.kill()
                    self._record_proc.wait(timeout=1.0)
                except Exception as kill_exc:  # noqa: BLE001
                    warnings.warn(
                        f"pw-record kill failed: {kill_exc}",
                        stacklevel=2,
                    )
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"pw-record terminate failed: {exc}", stacklevel=2)
        self._record_proc = None

    def _safe_join_drain_thread(self) -> None:
        thread = self._drain_thread
        if thread is None:
            return
        self._stop_drain.set()
        thread.join(timeout=2.0)
        self._drain_thread = None

    def _safe_join_drain_err_thread(self) -> None:
        """Join the stderr drain thread.

        No dedicated stop flag: the drain exits when ``pw-record``
        closes its stderr pipe, which is guaranteed by
        :meth:`_safe_terminate_record_proc` (always torn down before
        the data-plane joins in :meth:`close`). Keep that ordering or
        this join will block until the 2 s timeout.
        """
        thread = self._drain_err_thread
        if thread is None:
            return
        thread.join(timeout=2.0)
        self._drain_err_thread = None

    def _safe_join_event_thread(self) -> None:
        thread = self._event_thread
        if thread is None:
            return
        self._stop_events.set()
        if self._pulse is not None:
            # pulsectl exposes a thread-safe stop via event_listen_stop;
            # the flag is its public dropout signal. Calling both keeps
            # us aligned with the real pulsectl docs (which note that
            # event_listen_stop is racey on its own).
            try:
                self._pulse.event_listener_running = False  # pyright: ignore[reportAttributeAccessIssue]
            except Exception as exc:  # noqa: BLE001
                warnings.warn(
                    f"event_listener_running write failed: {exc}",
                    stacklevel=2,
                )
            try:
                self._pulse.event_listen_stop()  # pyright: ignore[reportUnknownMemberType]
            except Exception as exc:  # noqa: BLE001
                warnings.warn(
                    f"event_listen_stop failed: {exc}",
                    stacklevel=2,
                )
        thread.join(timeout=2.0)
        self._event_thread = None

    @override
    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True

        # Teardown order matters. The data plane is dismantled top-down
        # (event source → producer → consumer); the control plane is
        # then unwound bottom-up so each module always observes a
        # well-formed upstream/downstream:
        #
        # 1. Event listener first, so it can't fire a callback into a
        #    half-torn-down backend.
        # 2. pw-record next, which lets both drain threads observe EOF.
        # 3. Stdout drain joined first among the data plane, then the
        #    stderr drain — pw-record closes stderr after stdout.
        # 4. Null-sink unload. Removing the tap's ports lets PipeWire
        #    garbage-collect every pw-link we created, so no explicit
        #    unlink is needed. VRChat's own link to the default sink was
        #    never touched, so the user keeps hearing it throughout.
        # 5. State file after the module is gone — a concurrent
        #    janitor must never see the breadcrumb without its sink.
        # 6. Pulse control connection last (everything above needs it).
        self._safe_join_event_thread()
        self._safe_terminate_record_proc()
        self._safe_join_drain_thread()
        self._safe_join_drain_err_thread()
        self._safe_unload_null_sink()
        self._safe_remove_state_file()
        self._safe_close_pulse()
        self._pulse = None
