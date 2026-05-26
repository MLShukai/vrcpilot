"""Linux PipeWire-native speaker backend (per-PID).

Each :class:`PipeWireSpeakerBackend` instance owns three PipeWire
resources keyed by its VRChat ``pid``:

* a ``vrcpilot_tap_{pid}`` ``module-null-sink`` so multiple backends
  never share a capture sink;
* a ``module-loopback`` from the tap's monitor back to the resolved
  default sink so the user still hears VRChat at the speakers;
* a ``pw-record`` subprocess piping the monitor into a drain thread.

Routing replacement, not addition
---------------------------------

VRChat's ``sink_input`` is moved (via ``Pulse.sink_input_move``) onto
the per-pid tap, so its audio leaves the default sink entirely. The
loopback then brings it back to the default sink as a single
controlled path. The user's audible experience is unchanged from the
previous single-sink design, but the captures of two side-by-side
VRChat instances no longer leak into each other.

State / cleanup
---------------

A breadcrumb at
``$XDG_RUNTIME_DIR/vrcpilot/speaker-taps/{vrchat_pid}.json`` records
the module ids plus the VRChat process's ``create_time``. Start-up
idempotently sweeps tap modules whose VRChat PID is dead or has been
recycled (mismatched ``create_time``), so an ungraceful previous run
never wedges PipeWire.
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
import threading
import time
import warnings
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Final, override

import numpy as np
import psutil
from numpy.typing import NDArray

from vrcpilot.speaker.base import CHANNELS, SpeakerBackend

_logger = logging.getLogger(__name__)

#: External CLIs the backend relies on. Missing this is a hard
#: start-up failure with an actionable error message.
_REQUIRED_CLIS: Final[tuple[str, ...]] = ("pw-record",)

#: Match a ``vrcpilot_tap_<pid>`` null-sink argument. The trailing
#: ``\s`` anchors on PulseAudio's argument-token separator so e.g.
#: ``vrcpilot_tap_1234`` never spuriously matches ``vrcpilot_tap_12345``.
_NULL_SINK_RE: Final[re.Pattern[str]] = re.compile(r"sink_name=vrcpilot_tap_(\d+)\s")

#: Match a ``module-loopback`` whose source is one of our per-pid taps.
_LOOPBACK_RE: Final[re.Pattern[str]] = re.compile(
    r"source=vrcpilot_tap_(\d+)\.monitor\s"
)

#: Drain thread reads this many bytes per syscall. 4 KiB ≈ 10 ms of
#: stereo float32 @ 48 kHz, small enough to keep latency low but large
#: enough not to syscall every sample.
_DRAIN_CHUNK_BYTES: Final[int] = 4096

#: ``pulse.sink_list()`` can take a few ms to reflect a freshly loaded
#: ``module-null-sink``. Spin briefly before giving up.
_SINK_LOOKUP_RETRIES: Final[int] = 10
_SINK_LOOKUP_INTERVAL_SEC: Final[float] = 0.05

#: ``create_time`` tolerance when checking for PID reuse. ``psutil``
#: reports times in seconds; a small slack absorbs filesystem timestamp
#: rounding without letting an honest reuse slip through.
_CREATE_TIME_TOLERANCE_SEC: Final[float] = 0.05


def _tap_sink_name(pid: int) -> str:
    """Return the per-PID null-sink name used for ``pid``'s audio tap."""
    return f"vrcpilot_tap_{pid}"


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


def _loopback_args(pid: int, default_sink_name: str) -> str:
    """``module-loopback`` arguments bridging the per-pid tap's monitor back to
    the resolved default sink so the user keeps hearing VRChat.

    ``source_dont_move`` / ``sink_dont_move`` keep the loopback's
    endpoints pinned against accidental ``pavucontrol`` moves so a
    misclick cannot silently re-route VRChat audio away from the
    speakers.
    """
    return (
        f"source={_tap_sink_name(pid)}.monitor "
        f"sink={default_sink_name} "
        "source_dont_move=true sink_dont_move=true "
        "latency_msec=20 channels=2"
    )


def _pw_record_argv(pid: int) -> tuple[str, ...]:
    """Argv template for the ``pw-record`` subprocess of ``pid``'s tap.

    The trailing ``-`` writes raw PCM to stdout. Format / rate / channel
    count match :mod:`vrcpilot.speaker.base` exactly so no resampling
    is required.
    """
    return (
        "pw-record",
        f"--target={_tap_sink_name(pid)}.monitor",
        "--format=f32",
        "--rate=48000",
        "--channels=2",
        "--latency=20ms",
        "-",
    )


def _extract_tap_pid(module_name: str | None, argument: str | None) -> int | None:
    """Return the VRChat PID encoded in a vrcpilot tap module argument.

    Returns ``None`` when ``module_name`` / ``argument`` does not belong
    to one of our taps. The matcher anchors on the trailing
    whitespace PulseAudio emits between argument tokens so e.g.
    ``vrcpilot_tap_1234`` never accidentally matches ``vrcpilot_tap_12345``.
    """
    if not module_name or not argument:
        return None
    needle = argument.strip() + " "
    if module_name == "module-null-sink":
        m = _NULL_SINK_RE.search(needle)
    elif module_name == "module-loopback":
        m = _LOOPBACK_RE.search(needle)
    else:
        return None
    return int(m.group(1)) if m else None


class PipeWireSpeakerBackend(SpeakerBackend):
    """SpeakerBackend that captures one VRChat process via native PipeWire.

    Constructor performs the full per-pid setup under an ``ExitStack``
    so a partial start-up never leaks a null-sink, a loopback, or the
    ``pw-record`` subprocess. :meth:`close` is also registered with
    :func:`atexit` so an interpreter shutdown that bypasses
    ``__exit__`` still releases PipeWire resources.

    Args:
        read_timeout: Seconds :meth:`read` waits for the first chunk
            before returning empty. Must be ``> 0``.
        pid: Target VRChat PID. The backend creates a dedicated
            ``vrcpilot_tap_{pid}`` null-sink and moves only that
            process's sink_inputs onto it, so concurrent VRChat
            instances never share a tap. Callers (typically
            :class:`vrcpilot.speaker.Speaker`) supply a pre-resolved
            PID rather than re-resolving here.

    Raises:
        ValueError: ``read_timeout`` is not strictly positive.
        RuntimeError: The required CLI is missing, or the PulseAudio /
            PipeWire control plane refused the null-sink / loopback
            load, or the default sink name could not be resolved.
    """

    _read_timeout: float
    _pid: int
    _pulse: Any
    _null_sink_module_id: int | None
    _loopback_module_id: int | None
    _default_sink_name_at_load: str | None
    _state_file: Path | None
    _record_proc: Any
    _drain_thread: threading.Thread | None
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
        self._loopback_module_id = None
        self._default_sink_name_at_load = None
        self._state_file = None
        self._record_proc = None
        self._drain_thread = None
        self._event_thread = None
        self._stop_drain = threading.Event()
        self._stop_events = threading.Event()
        self._stdout_lock = threading.Lock()
        self._stdout_condition = threading.Condition(self._stdout_lock)
        self._buffer = bytearray()
        self._stdout_exception = None

        # Unwinds on failure: every successful step pushes a rollback
        # callback so a partial start-up never leaks a null-sink, a
        # loopback, or a pw-record subprocess.
        stack = ExitStack()
        try:
            self._pulse = self._open_pulse("vrcpilot-tap")
            stack.callback(self._safe_close_pulse)

            self._reset_stale_taps()

            self._null_sink_module_id = self._load_null_sink()
            stack.callback(self._safe_unload_null_sink)

            self._default_sink_name_at_load = self._resolve_default_sink_name()
            self._loopback_module_id = self._load_loopback(
                self._default_sink_name_at_load
            )
            # LIFO ordering: loopback unloads BEFORE null-sink so the
            # loopback never observes a deleted source.
            stack.callback(self._safe_unload_loopback)

            self._state_file = self._write_state_file()
            stack.callback(self._safe_remove_state_file)

            self._move_existing_streams_to_tap()

            self._record_proc = self._spawn_pw_record()
            stack.callback(self._safe_terminate_record_proc)

            self._drain_thread = threading.Thread(
                target=self._drain_stdout,
                name="PipeWireSpeakerDrain",
                daemon=True,
            )
            self._drain_thread.start()
            stack.callback(self._safe_join_drain_thread)

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

        Test seam (``mocker.patch.object``) — also keeps the
        ``pulsectl`` import local so non-Linux test runs never need it.
        """
        from pulsectl import (  # pyright: ignore[reportMissingTypeStubs]
            Pulse,
        )

        return Pulse(client_name)  # pyright: ignore[reportUnknownVariableType]

    def _spawn_pw_record(self) -> Any:
        """Spawn the ``pw-record`` subprocess piped to stdout.

        ``bufsize=0`` keeps the OS pipe un-double-buffered so the
        drain thread can pull at the latency we want. Test seam.
        """
        return subprocess.Popen(
            list(_pw_record_argv(self._pid)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    # ------------------------------------------------------------------
    # Start-up helpers
    # ------------------------------------------------------------------

    def _reset_stale_taps(self) -> None:
        """Unload leftover vrcpilot tap modules from prior runs.

        Sweeps both ``module-null-sink`` and ``module-loopback`` and
        decodes the VRChat PID from each argument. Unloads when:

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

        loopbacks: list[tuple[int, int]] = []
        null_sinks: list[tuple[int, int]] = []
        for module in modules:
            name_raw: Any = getattr(module, "name", None)
            arg_raw: Any = getattr(module, "argument", None)
            name = name_raw if isinstance(name_raw, str) else None
            arg = arg_raw if isinstance(arg_raw, str) else None
            pid = _extract_tap_pid(name, arg)
            if pid is None:
                continue
            index_raw: Any = getattr(module, "index", None)
            if not isinstance(index_raw, int):
                continue
            if name == "module-loopback":
                loopbacks.append((index_raw, pid))
            else:
                null_sinks.append((index_raw, pid))

        # Mirror close()'s teardown order: loopback before null-sink so
        # a loopback is never left pointing at a deleted source.
        for entries, module_name in (
            (loopbacks, "module-loopback"),
            (null_sinks, "module-null-sink"),
        ):
            for index, pid in entries:
                if self._tap_is_stale(pid):
                    self._unload_module_safely(index, module_name, pid)

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

    def _load_module(self, module_name: str, args: str, kind_label: str) -> int:
        """``pulse.module_load`` with shared ``isinstance(int)`` validation."""
        idx: Any = self._pulse.module_load(module_name, args)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        if not isinstance(idx, int):
            raise RuntimeError(
                f"module_load({kind_label}) returned non-int module id: "
                f"{type(idx).__name__}"
            )
        return idx

    def _load_null_sink(self) -> int:
        """Load the per-pid ``module-null-sink`` and return its index."""
        return self._load_module(
            "module-null-sink", _null_sink_args(self._pid), "null-sink"
        )

    def _resolve_default_sink_name(self) -> str:
        """Resolve the current default sink name for the loopback ``sink=``.

        Embedding the literal sink name (rather than ``@DEFAULT_SINK@``)
        avoids a PipeWire-Pulse placeholder-resolution edge that some
        distros disable. The trade-off is that the loopback does not
        follow a runtime default-sink change; that limitation is
        documented in the plan.
        """
        info: Any = self._pulse.server_info()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        name_raw: Any = getattr(info, "default_sink_name", None)
        if not isinstance(name_raw, str) or not name_raw:
            raise RuntimeError(
                "could not resolve default sink name from PipeWire server_info"
            )
        return name_raw

    def _load_loopback(self, default_sink_name: str) -> int:
        """Load the ``module-loopback`` and return its index."""
        return self._load_module(
            "module-loopback",
            _loopback_args(self._pid, default_sink_name),
            "loopback",
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
            "loopback_module_id": self._loopback_module_id,
            "sink_name": _tap_sink_name(self._pid),
            "default_sink_name_at_load": self._default_sink_name_at_load,
            "vrchat_pid": self._pid,
            "vrchat_create_time": vrchat_ct,
        }
        try:
            path.write_text(json.dumps(payload))
            return path
        except OSError as exc:
            warnings.warn(f"state file write failed: {exc}", stacklevel=2)
            return None

    def _resolve_tap_sink_index(self) -> int:
        """Return the per-pid sink's PulseAudio index, retrying briefly.

        PipeWire-Pulse can take a few ms to expose a freshly-loaded
        sink in ``sink_list()``. Spin a few times before giving up
        rather than racing the daemon.
        """
        target = _tap_sink_name(self._pid)
        for _ in range(_SINK_LOOKUP_RETRIES):
            sinks: list[Any]
            try:
                sinks = self._pulse.sink_list()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
            except Exception as exc:  # noqa: BLE001
                _logger.warning("sink_list failed: %s", exc)
                sinks = []
            for sink in sinks:
                name_raw: Any = getattr(sink, "name", None)
                if name_raw != target:
                    continue
                index_raw: Any = getattr(sink, "index", None)
                if isinstance(index_raw, int):
                    return index_raw
            time.sleep(_SINK_LOOKUP_INTERVAL_SEC)
        raise RuntimeError(
            f"could not resolve sink index for {target} after "
            f"{_SINK_LOOKUP_RETRIES} retries"
        )

    def _enumerate_vrchat_sink_inputs(self) -> list[int]:
        """Return ``sink_input.index`` for VRChat streams owned by
        ``self._pid``.

        Filter precedence:

        1. ``proplist['application.process.id']`` exact PID match.
        2. Proton/Wine fallback when ``process.id`` is absent: looks for
           ``application.process.binary == 'VRChat.exe'`` or
           ``'VRChat'`` substring in ``application.name``. Conservative:
           if multiple ambiguous streams exist alongside any PID-matched
           stream the ambiguous ones are dropped to avoid misrouting
           audio that might belong to a different VRChat instance.
        """
        try:
            inputs: list[Any] = self._pulse.sink_input_list()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("sink_input_list failed: %s", exc)
            return []

        matched: list[int] = []
        ambiguous: list[int] = []
        for inp in inputs:
            proplist_raw: Any = getattr(inp, "proplist", None)
            if not isinstance(proplist_raw, dict):
                continue
            proplist: dict[Any, Any] = proplist_raw  # pyright: ignore[reportUnknownVariableType]
            index_raw: Any = getattr(inp, "index", None)
            if not isinstance(index_raw, int):
                continue

            proc_id_raw: Any = proplist.get("application.process.id")
            proc_id: int | None
            if proc_id_raw is None:
                proc_id = None
            else:
                try:
                    proc_id = int(proc_id_raw)
                except (TypeError, ValueError):
                    proc_id = None

            if proc_id is not None:
                if proc_id == self._pid:
                    matched.append(index_raw)
                continue

            binary: Any = proplist.get("application.process.binary")
            app_name_raw: Any = proplist.get("application.name") or ""
            looks_like_vrchat = binary == "VRChat.exe" or "VRChat" in str(app_name_raw)
            if looks_like_vrchat:
                ambiguous.append(index_raw)

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
            "inputs to avoid misrouted audio.",
            len(ambiguous),
            self._pid,
        )
        return matched

    def _move_existing_streams_to_tap(self) -> None:
        """Move every matching VRChat sink_input onto the per-pid tap.

        Idempotent: an input already routed to our tap stays put.
        Failures are logged rather than raised so a transient daemon
        hiccup never fails the whole startup.
        """
        try:
            sink_idx = self._resolve_tap_sink_index()
        except RuntimeError as exc:
            _logger.warning("tap sink not yet visible, skipping moves: %s", exc)
            return
        for inp_idx in self._enumerate_vrchat_sink_inputs():
            try:
                self._pulse.sink_input_move(inp_idx, sink_idx)  # pyright: ignore[reportUnknownMemberType]
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "sink_input_move %d -> %d failed: %s",
                    inp_idx,
                    sink_idx,
                    exc,
                )

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
        """Re-move VRChat streams onto the tap when a new ``sink_input``
        appears.

        Pulsectl callback. Failures are logged but swallowed — the
        listener must keep running. Honours :attr:`_stop_events` as the
        exit signal back into :meth:`_listen_events`.
        """
        if self._stop_events.is_set():
            try:
                self._pulse.event_listener_running = False  # pyright: ignore[reportAttributeAccessIssue]
            except Exception as exc:  # noqa: BLE001
                _logger.warning("event_listener_running write failed: %s", exc)
            return
        facility = getattr(event, "facility", None)
        event_type = getattr(event, "t", None)
        if facility != "sink_input" or event_type != "new":
            return
        try:
            self._move_existing_streams_to_tap()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("auto-move failed for event %s: %s", event, exc)

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

    def _safe_unload_by_attr(self, attr_name: str, module_label: str) -> None:
        """Shared body of the two ``_safe_unload_*`` teardown methods.

        Keeps the per-method names stable for ``ExitStack.callback`` /
        ``close()`` while collapsing the pulse-call + warning + clear
        logic into one place.
        """
        module_id = getattr(self, attr_name)
        if module_id is None or self._pulse is None:
            return
        try:
            self._pulse.module_unload(module_id)  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"{module_label} unload failed: {exc}", stacklevel=2)
        setattr(self, attr_name, None)

    def _safe_unload_loopback(self) -> None:
        self._safe_unload_by_attr("_loopback_module_id", "module-loopback")

    def _safe_unload_null_sink(self) -> None:
        self._safe_unload_by_attr("_null_sink_module_id", "module-null-sink")

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

        # Teardown order matters:
        # 1. Event listener first, so it can't fire a callback into a
        #    half-torn-down backend.
        # 2. pw-record next, which lets the drain thread observe EOF.
        # 3. Drain thread last among the data plane, joined cleanly.
        # 4. Loopback BEFORE null-sink so the loopback never sees a
        #    deleted source (and PipeWire stops re-routing instantly).
        # 5. Null-sink unload. PulseAudio re-routes VRChat's sink_input
        #    back to the default sink automatically when the sink it
        #    was moved to disappears, so no explicit move-back is
        #    needed and the user keeps hearing VRChat.
        # 6. State file after both modules are gone — a concurrent
        #    janitor must never see the breadcrumb without its sink.
        # 7. Pulse control connection last.
        self._safe_join_event_thread()
        self._safe_terminate_record_proc()
        self._safe_join_drain_thread()
        self._safe_unload_loopback()
        self._safe_unload_null_sink()
        self._safe_remove_state_file()
        self._safe_close_pulse()
        self._pulse = None
