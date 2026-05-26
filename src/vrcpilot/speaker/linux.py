"""Linux PipeWire-native speaker backend (per-PID).

Each :class:`PipeWireSpeakerBackend` instance owns two PipeWire
resources keyed by its VRChat ``pid``:

* a ``vrcpilot_tap_{pid}`` ``module-null-sink`` so multiple backends
  never share a capture sink;
* a ``pw-record`` subprocess piping the monitor into a drain thread.

Routing replacement (no monitor bridge)
---------------------------------------

VRChat's ``sink_input`` is *moved* onto the per-pid tap via
``Pulse.sink_input_move`` — the stream's link to the default sink is
replaced, not duplicated. The backend deliberately does **not** load a
``module-loopback`` from the tap monitor back to the default sink:
the previous design did so and was the load-bearing leak that broke
per-PID separation when two VRChat instances were captured at once.
**Therefore while recording is active the user no longer hears VRChat
audio through the default speakers** — this is a known UX trade-off
for isolation correctness, not a bug. When :meth:`close` unloads the
null-sink, PulseAudio auto-routes the sink_input back to the default
sink, so VRChat audio returns to the user's speakers without an
explicit move-back.

Diagnostic surface
------------------

Routing decisions are observable from the log stream alone. Every
VRChat-like ``sink_input`` is logged at INFO with a pipe-delimited
schema, each ``sink_input_move`` is post-verified by re-querying the
input's live ``sink`` (mismatches surface auto-routing policies that
returned API-success while reverting the move), and ``pw-record``'s
stderr is forwarded line-by-line (so target-node fallbacks and ALSA
errors are not lost to the subprocess's own stream). This contract is
what the Phase A e2e captures rely on for post-mortem reconstruction.

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
            are moved onto it, so concurrent VRChat instances stay
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

            self._move_existing_streams_to_tap()

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
        """Return ``sink_input.index`` values for VRChat streams of
        ``self._pid``.

        Filter precedence:

        1. ``proplist['application.process.id']`` exact PID match.
        2. Proton/Wine fallback when ``process.id`` is absent: looks for
           ``application.process.binary == 'VRChat.exe'`` or
           ``'VRChat'`` substring in ``application.name`` /
           ``media.name``. Conservative: if multiple ambiguous streams
           exist alongside any PID-matched stream the ambiguous ones
           are dropped to avoid misrouting audio that might belong to
           a different VRChat instance.

        Diagnostic contract: every VRChat-like candidate emits one
        ``sink_input candidate | ...`` INFO line and the call ends with
        a single ``sink_input scan summary | ...`` line. Tests and the
        Phase A e2e captures depend on those prefixes existing so a
        post-mortem can reconstruct which streams the routing layer
        saw and how each was classified — change the prefix or schema
        only with the diagnostic consumers in mind.
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
            proc_id: int | None
            if proc_id_raw is None:
                proc_id = None
            else:
                try:
                    proc_id = int(proc_id_raw)
                except (TypeError, ValueError):
                    proc_id = None

            binary_raw: Any = proplist.get("application.process.binary")
            binary: str | None = binary_raw if isinstance(binary_raw, str) else None
            app_name_raw: Any = proplist.get("application.name")
            app_name: str | None = (
                app_name_raw if isinstance(app_name_raw, str) else None
            )
            host_raw: Any = proplist.get("application.process.host")
            host: str | None = host_raw if isinstance(host_raw, str) else None
            media_name_raw: Any = proplist.get("media.name")
            media_name: str | None = (
                media_name_raw if isinstance(media_name_raw, str) else None
            )
            current_sink_raw: Any = getattr(inp, "sink", None)
            current_sink: int | None = (
                current_sink_raw if isinstance(current_sink_raw, int) else None
            )

            looks_like_vrchat = (
                binary == "VRChat.exe"
                or (app_name is not None and "VRChat" in app_name)
                or (media_name is not None and "VRChat" in media_name)
            )

            classification: str
            if proc_id is not None and proc_id == self._pid:
                matched.append(index_raw)
                classification = "matched"
            elif proc_id is None and looks_like_vrchat:
                ambiguous.append(index_raw)
                classification = "ambiguous"
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
                "current_sink_index=%s | self_pid=%d | classification=%s",
                index_raw,
                proc_id_raw,
                proc_id,
                binary,
                app_name,
                host,
                media_name,
                current_sink,
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
            "inputs to avoid misrouted audio.",
            len(ambiguous),
            self._pid,
        )
        return matched

    def _move_existing_streams_to_tap(self) -> None:
        """Move every matching VRChat sink_input onto the per-pid tap.

        Uses ``Pulse.sink_input_move`` — a *replacement* of the input's
        routing, not an added link. After the move VRChat's audio
        leaves the default sink entirely (see module docstring); the
        per-pid null-sink is the only path that sees the stream.

        Every successful ``sink_input_move`` is post-verified by
        :meth:`_verify_sink_input_moved`. The verification exists
        because ``pulsectl.sink_input_move`` can return success while
        the PipeWire-Pulse bridge silently fails to apply the move
        (auto-routing policies, ``stream.target`` hints set by the
        client, or session-manager policy can all revert the route
        without surfacing an error on the call site). Without the
        re-query the only symptom would be "the recording is empty
        even though startup logged success".

        Idempotent: an input already routed to our tap stays put.
        Per-input move failures are logged at WARNING and the loop
        continues so a transient daemon hiccup on one stream never
        aborts the whole startup.
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
                continue
            self._verify_sink_input_moved(inp_idx, sink_idx)

    def _verify_sink_input_moved(self, inp_idx: int, expected_sink_idx: int) -> None:
        """Re-query the sink_input and warn if its sink does not match.

        Exists because ``sink_input_move`` can succeed at the pulsectl
        API boundary while the underlying PipeWire-Pulse layer leaves
        the route on whichever sink the session manager last decided
        — the only reliable detector is reading the input's live
        ``sink`` field back. Tests assert on the ``post-verify ok`` /
        ``post-verify failed`` log prefixes, so they double as the
        diagnostic contract.

        The ``sink_input_info`` lookup can itself fail (e.g. the input
        disappeared between move and verify); that case is downgraded
        to a ``post-verify query failed`` WARNING so the move loop
        keeps going for the surviving inputs.
        """
        try:
            info: Any = self._pulse.sink_input_info(inp_idx)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "sink_input_move post-verify query failed | "
                "sink_input_index=%d | self_pid=%d | error=%s",
                inp_idx,
                self._pid,
                exc,
            )
            return
        actual_sink_raw: Any = getattr(info, "sink", None)
        actual_sink: int | None = (
            actual_sink_raw if isinstance(actual_sink_raw, int) else None
        )
        if actual_sink == expected_sink_idx:
            _logger.info(
                "sink_input_move post-verify ok | sink_input_index=%d | "
                "sink_index=%d | self_pid=%d",
                inp_idx,
                expected_sink_idx,
                self._pid,
            )
        else:
            _logger.warning(
                "sink_input_move post-verify failed | "
                "sink_input_index=%d | expected_sink_index=%d | "
                "actual_sink_index=%s | self_pid=%d",
                inp_idx,
                expected_sink_idx,
                actual_sink,
                self._pid,
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

    def _drain_stderr(self) -> None:
        """Drain ``pw-record`` stderr line-by-line into :data:`_logger`.

        Background-thread body. Exits on EOF / read error.

        Exists because ``pw-record`` will *silently* fall back to a
        different source when its ``--target=...`` argument can't be
        resolved (the resolver picks whichever node the session
        manager considers nearest), and the only signal of that fallback
        is a single stderr line. Without this drain the backend would
        keep producing audio from the wrong sink with no visible error
        — every line is forwarded at INFO under the ``pw-record stderr
        | ...`` prefix so target-node fallbacks, ALSA / PipeWire
        connection errors, and xrun warnings show up in the same log
        stream as the routing diagnostics.

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
        """Re-route freshly-created VRChat ``sink_input``s onto the tap.

        Without this callback, a new sink_input that VRChat creates
        mid-session (e.g. when the user opens a UI dialog with its own
        audio stream) would land on the default sink and bypass the
        capture entirely.

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
        # 4. Null-sink unload. When the sink VRChat's sink_input was
        #    moved to disappears, PulseAudio auto-routes the input back
        #    to the default sink, so no explicit move-back is needed —
        #    the user hears VRChat again without a gap.
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
