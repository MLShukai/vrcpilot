"""Linux PipeWire-native speaker backend.

Splits the work across three planes so a crash in one cannot wedge
the others:

* Control plane -- ``pulsectl.Pulse`` (libpulse via ctypes) loads /
  unloads the ``vrcpilot_tap`` null-sink and subscribes to
  ``sink_input`` events for late-joining VRChat streams.
* Data plane -- ``pw-record --target=vrcpilot_tap.monitor`` runs
  out-of-process and writes interleaved ``float32`` LE / 48 kHz /
  stereo to its stdout, which a background thread drains into a
  shared buffer. Matches the constants in
  :mod:`vrcpilot.speaker.base` so no resampling is needed.
* Routing -- additive ``pw-link`` calls from every VRChat
  ``Stream/Output/Audio`` node's ``output_FL`` / ``output_FR`` to the
  tap's playback ports. The user's existing links to real speakers
  are left alone, so VRChat is still audible while we record.

A breadcrumb at ``$XDG_RUNTIME_DIR/vrcpilot/tap.json`` carries the
PID + module id so an out-of-band janitor can unload the null-sink
after an ungraceful exit; start-up also idempotently unloads any
leftover ``vrcpilot_tap`` module from a previous crashed run.

``pulsectl`` is imported lazily inside :meth:`_open_pulse` so
non-Linux platforms never need it installed.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise RuntimeError("PipeWireSpeakerBackend is Linux-only")

import atexit
import json
import logging
import os
import shutil
import subprocess
import threading
import warnings
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Final, override

import numpy as np
from numpy.typing import NDArray

from vrcpilot import process
from vrcpilot.speaker.base import CHANNELS, SpeakerBackend

_logger = logging.getLogger(__name__)

#: External CLIs the backend relies on. Missing any of these is a hard
#: start-up failure with an aggregated, actionable error message.
_REQUIRED_CLIS: Final[tuple[str, ...]] = ("pw-record", "pw-link", "pw-dump")

#: Deterministic null-sink name. Stale instances from previous crashed
#: runs are unloaded on start-up by matching this token in the module's
#: ``argument`` string.
_TAP_SINK_NAME: Final[str] = "vrcpilot_tap"

#: PulseAudio module-null-sink load argument. Mirrors the channel /
#: rate / format the rest of the speaker stack assumes
#: (see :mod:`vrcpilot.speaker.base`).
_NULL_SINK_ARGS: Final[str] = (
    f"sink_name={_TAP_SINK_NAME} "
    "sink_properties=device.description=VRCPilotTap "
    "rate=48000 channels=2 format=float32le"
)

#: pw-record argv template; ``--target`` is the null-sink's monitor
#: source. The trailing ``-`` writes raw PCM to stdout.
_PW_RECORD_ARGV: Final[tuple[str, ...]] = (
    "pw-record",
    f"--target={_TAP_SINK_NAME}.monitor",
    "--format=f32",
    "--rate=48000",
    "--channels=2",
    "--latency=20ms",
    "-",
)

#: Drain thread reads this many bytes per syscall. 4 KiB ≈ 10 ms of
#: stereo float32 @ 48 kHz, small enough to keep latency low but large
#: enough not to syscall every sample.
_DRAIN_CHUNK_BYTES: Final[int] = 4096


class PipeWireSpeakerBackend(SpeakerBackend):
    """SpeakerBackend that captures VRChat audio via native PipeWire on Linux.

    Linux-only. The constructor performs the full three-plane setup
    described in the module docstring:

    1. Verify required CLIs are on ``$PATH`` (``pw-record``,
       ``pw-link``, ``pw-dump``, ``pactl``) and resolve VRChat's PID.
    2. Open a ``pulsectl`` connection, unload any stale
       ``vrcpilot_tap`` null-sink, then load a fresh one. The user
       keeps hearing VRChat on their real speakers because the
       existing graph is untouched -- we only *add* links into the
       tap.
    3. Spawn ``pw-record`` against the tap's monitor source, drain
       its stdout from a background thread, and subscribe to
       ``sink_input`` events so VRChat streams created mid-session
       get auto-linked too.

    Every successful step registers a rollback callback on an
    ``ExitStack``; a partial start-up never leaks a null-sink or a
    ``pw-record`` subprocess. :meth:`close` runs the same cleanup in
    teardown order and is registered with :func:`atexit` so an
    interpreter exit cannot strand the null-sink either.

    Args:
        read_timeout: Per-:meth:`read` timeout in seconds. A quiet
            VRChat stream surfaces as an empty ``(0, CHANNELS)`` ndarray
            rather than an exception. Must be strictly positive.

    Raises:
        ValueError: ``read_timeout`` is not strictly positive.
        RuntimeError: A required CLI is missing, VRChat is not running,
            or the PulseAudio / PipeWire control plane refused the
            null-sink load.
    """

    _read_timeout: float
    _pid: int
    _pulse: Any
    _null_sink_module_id: int | None
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

    def __init__(self, *, read_timeout: float = 2.0) -> None:
        if read_timeout <= 0:
            raise ValueError(f"read_timeout must be > 0 (got {read_timeout})")

        missing = [c for c in _REQUIRED_CLIS if shutil.which(c) is None]
        if missing:
            raise RuntimeError(
                f"PipeWire backend requires {_REQUIRED_CLIS}; missing: {missing}. "
                "Install 'pipewire' and 'pipewire-pulse' (or distro equivalents)."
            )

        pid = process.find_pid()
        if pid is None:
            raise RuntimeError("VRChat is not running")

        self._read_timeout = read_timeout
        self._pid = pid
        self._closed = False
        self._lock = threading.Lock()
        self._null_sink_module_id = None
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
        # callback so a partial start-up never leaks a null-sink or
        # leaves a pw-record subprocess running.
        stack = ExitStack()
        try:
            self._pulse = self._open_pulse("vrcpilot-tap")
            stack.callback(self._safe_close_pulse)

            self._reset_stale_modules()

            self._null_sink_module_id = self._load_null_sink()
            stack.callback(self._safe_unload_null_sink)

            self._state_file = self._write_state_file(self._null_sink_module_id)
            stack.callback(self._safe_remove_state_file)

            self._link_existing_streams()

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

        Test seam: substituted via :func:`mocker.patch.object` with a
        duck-typed :class:`tests.fakes.FakePulse`. The import is local
        so non-Linux test runs do not require ``pulsectl``.
        """
        from pulsectl import (  # pyright: ignore[reportMissingTypeStubs]
            Pulse,
        )

        return Pulse(client_name)  # pyright: ignore[reportUnknownVariableType]

    def _run_pw_dump(self) -> list[Any]:
        """Return the parsed ``pw-dump`` JSON array.

        Test seam: tests substitute a fixture-driven list of dicts
        mirroring real ``pw-dump`` output so no PipeWire daemon is
        needed.
        """
        result = subprocess.run(
            ["pw-dump"],
            check=True,
            capture_output=True,
            text=True,
        )
        parsed: Any = json.loads(result.stdout)
        if not isinstance(parsed, list):
            raise RuntimeError(f"pw-dump returned non-array JSON: {type(parsed)}")
        return parsed  # pyright: ignore[reportUnknownVariableType]

    def _run_pw_link(self, source: str, target: str) -> None:
        """Invoke ``pw-link <source> <target>``.

        ``check=False`` because PipeWire reaps gone nodes async, so a
        missing endpoint at link time is not fatal. Test seam: a
        recording :class:`unittest.mock.MagicMock` replaces this.
        """
        subprocess.run(["pw-link", source, target], check=False)

    def _spawn_pw_record(self) -> Any:
        """Spawn the ``pw-record`` subprocess piped to stdout.

        ``bufsize=0`` keeps the OS pipe un-double-buffered so the
        :meth:`_drain_stdout` thread can pull 4 KiB chunks at the
        latency we want. Test seam: substituted with
        :class:`tests.fakes.FakePwRecordProcess`.
        """
        return subprocess.Popen(
            list(_PW_RECORD_ARGV),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    # ------------------------------------------------------------------
    # Start-up helpers
    # ------------------------------------------------------------------

    def _reset_stale_modules(self) -> None:
        """Unload any leftover ``vrcpilot_tap`` null-sink from a prior crash.

        Matches by the ``sink_name=`` token in the module's ``argument``
        string so we never unload an unrelated ``module-null-sink``.
        """
        try:
            modules: list[Any] = self._pulse.module_list()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("module_list failed during stale reset: %s", exc)
            return
        for module in modules:
            name = getattr(module, "name", None)
            arg = getattr(module, "argument", None) or ""
            if name == "module-null-sink" and f"sink_name={_TAP_SINK_NAME}" in arg:
                index = getattr(module, "index", None)
                if not isinstance(index, int):
                    continue
                try:
                    self._pulse.module_unload(index)  # pyright: ignore[reportUnknownMemberType]
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "Failed to unload stale module-null-sink %d: %s", index, exc
                    )

    def _load_null_sink(self) -> int:
        """Load the ``vrcpilot_tap`` null-sink and return its index."""
        idx: Any = self._pulse.module_load("module-null-sink", _NULL_SINK_ARGS)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        if not isinstance(idx, int):
            raise RuntimeError(
                f"module_load returned non-int module id: {type(idx).__name__}"
            )
        return idx

    def _resolve_state_dir(self) -> Path:
        """Return (and create) the directory the state file lives in.

        ``$XDG_RUNTIME_DIR/vrcpilot`` when the env var is set, otherwise
        ``/tmp/vrcpilot-{uid}`` so the backend still has a stable path
        on minimal systems where the runtime dir is missing.
        """
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime:
            base = Path(runtime) / "vrcpilot"
        else:
            uid = os.getuid() if hasattr(os, "getuid") else 0
            base = Path(f"/tmp/vrcpilot-{uid}")
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _write_state_file(self, module_id: int) -> Path | None:
        """Persist the PID + module id so external janitors can recover.

        Best-effort: write failures degrade to ``None`` with a warning.
        The state file is only a recovery aid for crashes -- normal
        shutdown still releases the sink via :meth:`close`.
        """
        try:
            state_dir = self._resolve_state_dir()
            state_file = state_dir / "tap.json"
            payload = {
                "pid": os.getpid(),
                "module_id": module_id,
                "sink_name": _TAP_SINK_NAME,
            }
            state_file.write_text(json.dumps(payload))
            return state_file
        except OSError as exc:
            warnings.warn(
                f"state file write failed: {exc}",
                stacklevel=2,
            )
            return None

    def _enumerate_vrchat_nodes(self) -> list[str]:
        """Return ``node.name`` for every active VRChat audio output.

        VRChat typically exposes one output node but can surface
        multiple (voice / music submix), so we link every match.
        """
        try:
            dump = self._run_pw_dump()
        except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
            _logger.warning("pw-dump failed: %s", exc)
            return []

        names: list[str] = []
        for entry in dump:
            if not isinstance(entry, dict):
                continue
            entry_dict: dict[Any, Any] = entry  # pyright: ignore[reportUnknownVariableType]
            info: Any = entry_dict.get("info")
            if not isinstance(info, dict):
                continue
            info_dict: dict[Any, Any] = info  # pyright: ignore[reportUnknownVariableType]
            props: Any = info_dict.get("props")
            if not isinstance(props, dict):
                continue
            props_dict: dict[Any, Any] = props  # pyright: ignore[reportUnknownVariableType]
            media_class: Any = props_dict.get("media.class")
            if media_class != "Stream/Output/Audio":
                continue
            binary: Any = props_dict.get("application.process.binary")
            app_name: Any = props_dict.get("application.name", "") or ""
            if binary != "VRChat.exe" and "VRChat" not in str(app_name):
                continue
            node_name: Any = props_dict.get("node.name")
            if isinstance(node_name, str):
                names.append(node_name)
        return names

    def _link_existing_streams(self) -> None:
        """Link every currently-active VRChat output node to the tap."""
        for node in self._enumerate_vrchat_nodes():
            for channel in ("FL", "FR"):
                src = f"{node}:output_{channel}"
                dst = f"{_TAP_SINK_NAME}:playback_{channel}"
                try:
                    self._run_pw_link(src, dst)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("pw-link %s -> %s failed: %s", src, dst, exc)

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
        # sample buffered since the previous call (mirrors proc-tap's
        # drain-all-queued-chunks behaviour). Drain-thread errors are
        # checked under the same condition both before and after the
        # wait so an exception planted concurrently with the wait is
        # never silently dropped (the producer-side notify could race
        # an unguarded pre-wait check).
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
                "pw-record returned %d float32 samples not divisible by %d "
                "channels; dropping %d trailing samples.",
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
        ``False``. Errors are logged but never propagated -- a dead
        event listener must not take down the data plane.
        """
        try:
            self._pulse.event_mask_set("sink_input")  # pyright: ignore[reportUnknownMemberType]
            self._pulse.event_callback_set(self._on_pulse_event)  # pyright: ignore[reportUnknownMemberType]
            self._pulse.event_listen()  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("pulse event listener exited: %s", exc)

    def _on_pulse_event(self, event: Any) -> None:
        """Re-link VRChat streams when a new ``sink_input`` appears.

        Pulsectl callback. Failures are logged but swallowed -- the
        listener must keep running. Also honours :attr:`_stop_events`
        as the exit signal back into :meth:`_listen_events`.
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
            self._link_existing_streams()
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
        # _stop_drain is owned by _safe_join_drain_thread; terminate
        # itself causes pw-record to close its stdout and unblock the
        # drain loop, which is the only signal that actually wakes
        # ``stdout.read``.
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
        # 4. Null-sink unload so the user's graph stops routing into a
        #    dead tap.
        # 5. State file after the sink is gone -- a concurrent janitor
        #    must never see the breadcrumb without its sink.
        # 6. Pulse control connection last.
        self._safe_join_event_thread()
        self._safe_terminate_record_proc()
        self._safe_join_drain_thread()
        self._safe_unload_null_sink()
        self._safe_remove_state_file()
        self._safe_close_pulse()
        self._pulse = None
