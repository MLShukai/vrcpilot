"""Audio-related test doubles.

Stand-ins mirroring the speaker modality's public surface:

* :class:`FakeSpeaker` mirrors the public
  :class:`vrcpilot.speaker.session.Speaker` surface (``read`` / ``close``
  / context manager). Used by :class:`vrcpilot.speaker.loop.SpeakerLoop`
  tests where the loop's threading machinery is exercised against a
  deterministic chunk source.

* :class:`FakeProcessAudioCapture` mirrors the
  :class:`proctap.ProcessAudioCapture` surface that
  :class:`vrcpilot.speaker.proctap.ProcTapSpeakerBackend` actually
  invokes (``start`` / ``stop`` / ``close`` / ``read(timeout)``). The
  backend exposes a single factory method, ``_open_capture``, that the
  production path overrides to call ``proctap``. Tests patch that
  factory to return a :class:`FakeProcessAudioCapture` so the
  ``read`` / ``close`` paths can be exercised without touching real
  audio hardware.

* :class:`FakePulse` / :class:`FakePulseModuleInfo` /
  :class:`FakePulseEventInfo` mirror the slice of the ``pulsectl.Pulse``
  surface that
  :class:`vrcpilot.speaker.pipewire.PipeWireSpeakerBackend` invokes
  (``module_list`` / ``module_load`` / ``module_unload`` /
  ``event_mask_set`` / ``event_callback_set`` / ``event_listen`` /
  ``event_listen_stop`` / ``close`` / ``connected`` /
  ``event_listener_running``). Tests patch ``pulsectl.Pulse`` to
  return a :class:`FakePulse` and use :meth:`FakePulse.emit_event` to
  synchronously drive the registered callback without standing up a
  real PulseAudio / PipeWire server.

* :class:`FakePwRecordProcess` mirrors the slice of the
  :class:`subprocess.Popen` surface that the PipeWire backend uses to
  drive ``pw-record`` (``stdout.read`` / ``poll`` / ``terminate`` /
  ``wait`` / ``kill`` / ``returncode`` / ``stderr``). Tests patch
  ``subprocess.Popen`` to return a :class:`FakePwRecordProcess` and
  drive the drain thread via :meth:`FakePwRecordProcess.emit_pcm` /
  :meth:`FakePwRecordProcess.close_stdout`.

* :class:`FakeSpeakerLoop` / :class:`FakeWavSink` /
  :class:`FakeRawPcmStdoutSink` mirror the CLI-facing
  :class:`vrcpilot.speaker.SpeakerLoop` /
  :class:`vrcpilot.speaker.WavFileSink` /
  :class:`vrcpilot.speaker.RawPcmStdoutSink` so ``vrcpilot.cli.record``
  tests can run without proc-tap (and without touching the filesystem
  or stdout). Each mirrors :mod:`tests.fakes.capture` 1:1 (``instances``
  class-level list, ``frames_per_start`` / ``init_side_effect``
  knobs).

The fakes only implement methods production actually calls; the
``feedback_fakes_mirror_production`` rule in the project memory
applies.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Self

import numpy as np
from numpy.typing import NDArray

from vrcpilot.speaker.base import CHANNELS


class FakeProcessAudioCapture:
    """Duck-typed stand-in for :class:`proctap.ProcessAudioCapture`.

    Backed by an in-memory FIFO of ``bytes`` chunks (proc-tap's native
    return type). ``emit_samples`` queues one chunk in float32 ndarray
    form and converts it to interleaved bytes the way proc-tap does;
    tests can also push raw bytes via :attr:`enqueue_bytes` when they
    need to drive the truncation branch of the backend.
    """

    def __init__(self, *, pid: int) -> None:
        self.pid = pid
        self.start_calls: int = 0
        self.stop_calls: int = 0
        self.close_calls: int = 0
        self.read_calls: int = 0
        self.stop_raises: BaseException | None = None
        self.close_raises: BaseException | None = None
        self._queue: deque[bytes] = deque()

    def emit_samples(self, samples: NDArray[np.float32]) -> None:
        """Queue ``samples`` (shape ``(N, CHANNELS)``) as one proc-tap chunk.

        The samples are flattened to interleaved float32 little-endian
        bytes, which is the format proc-tap delivers on Windows.
        """
        if samples.ndim != 2 or samples.shape[1] != CHANNELS:
            raise ValueError(
                f"emit_samples expects shape (N, {CHANNELS}), got {samples.shape}"
            )
        if samples.dtype != np.float32:
            raise ValueError(f"emit_samples expects float32, got dtype={samples.dtype}")
        self._queue.append(samples.tobytes())

    def enqueue_bytes(self, payload: bytes) -> None:
        """Queue a raw byte payload (advanced; bypasses shape checks)."""
        self._queue.append(payload)

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1
        if self.stop_raises is not None:
            raise self.stop_raises

    def close(self) -> None:
        self.close_calls += 1
        if self.close_raises is not None:
            raise self.close_raises

    def read(self, timeout: float) -> bytes | None:
        """Pop the next queued chunk or ``None`` if the queue is empty.

        ``timeout`` is accepted for signature parity with proc-tap; the
        fake never blocks because tests load the queue synchronously.
        """
        del timeout
        self.read_calls += 1
        if not self._queue:
            return None
        return self._queue.popleft()


@dataclass
class FakePulseModuleInfo:
    """Duck-typed stand-in for ``pulsectl.PulseModuleInfo``.

    Mirrors the three attributes the PipeWire speaker backend reads:
    the numeric ``index`` assigned by the server, the module ``name``
    (e.g. ``"module-null-sink"``), and the raw ``argument`` string
    that was passed to ``module_load``.
    """

    index: int
    name: str
    argument: str


@dataclass
class FakePulseEventInfo:
    """Duck-typed stand-in for ``pulsectl.PulseEventInfo``.

    Mirrors the three attributes the backend's event callback reads:
    the event type ``t`` (``"new"`` / ``"change"`` / ``"remove"``), the
    PulseAudio facility ``facility`` (e.g. ``"sink_input"``), and the
    facility-scoped object ``index``.
    """

    t: str
    facility: str
    index: int


class FakePulse:
    """Duck-typed stand-in for :class:`pulsectl.Pulse`.

    Backs a minimal in-memory model of the PulseAudio control plane the
    PipeWire speaker backend touches: a list of loaded modules, an event
    subscription with a registered callback, and a blocking
    :meth:`event_listen` that tests release explicitly.

    The fake is deliberately threading-light: :meth:`event_listen`
    parks on a :class:`threading.Event` and tests synchronously fire
    callbacks via :meth:`emit_event`. This keeps unit tests
    deterministic and avoids the real ``pulsectl`` ctypes binding (so
    the fake can be imported on machines without ``pulsectl``
    installed).

    Args:
        client_name: Forwarded to the production :class:`pulsectl.Pulse`
            constructor; recorded as :attr:`client_name` so tests can
            assert the backend identified itself correctly.

    Attributes:
        client_name: The constructor argument, verbatim.
        modules: Currently-loaded modules. Tests can pre-seed entries
            to exercise stale-module cleanup paths.
        module_load_calls: ``(name, argument)`` tuples recording every
            :meth:`module_load` invocation, in order.
        module_unload_calls: Module indices passed to
            :meth:`module_unload`, in order.
        event_calls: ``(t, facility, index)`` tuples recording every
            event the test pushed via :meth:`emit_event`.
        event_masks: Last facility list passed to
            :meth:`event_mask_set` (empty until first set).
        event_callback: Currently-registered event callback, or
            ``None``.
        event_listener_running: Mirrors the ``pulsectl`` flag the
            backend's callback can toggle to break out of
            :meth:`event_listen`. Production code reads/writes this
            attribute directly.
        connected: ``True`` until :meth:`close` is called.
        closed: ``True`` after :meth:`close`. ``connected`` is the
            inverse.
        next_module_id: Monotonic counter used to assign indices on
            :meth:`module_load`. Tests can inspect or set this to
            steer scenarios.
    """

    def __init__(self, client_name: str) -> None:
        self.client_name = client_name
        self.modules: list[FakePulseModuleInfo] = []
        self.module_load_calls: list[tuple[str, str]] = []
        self.module_unload_calls: list[int] = []
        self.event_calls: list[tuple[str, str, int]] = []
        self.event_masks: tuple[str, ...] = ()
        self.event_callback: Callable[[FakePulseEventInfo], None] | None = None
        self.event_listener_running: bool = False
        self.closed: bool = False
        self.next_module_id: int = 0
        self._listen_release = threading.Event()

    @property
    def connected(self) -> bool:
        return not self.closed

    def _check_open(self) -> None:
        if self.closed:
            raise RuntimeError("pulse is closed")

    def module_list(self) -> list[FakePulseModuleInfo]:
        """Return a shallow copy of the currently-loaded modules."""
        self._check_open()
        return list(self.modules)

    def module_load(self, name: str, args: str) -> int:
        """Append a module entry and return its newly-assigned index."""
        self._check_open()
        self.module_load_calls.append((name, args))
        index = self.next_module_id
        self.next_module_id += 1
        self.modules.append(FakePulseModuleInfo(index=index, name=name, argument=args))
        return index

    def module_unload(self, index: int) -> None:
        """Remove the module with ``index`` from :attr:`modules`.

        Silently no-ops if the index is unknown -- matching the
        real ``pulsectl`` behaviour when the server has already
        reaped the module.
        """
        self._check_open()
        self.module_unload_calls.append(index)
        self.modules = [m for m in self.modules if m.index != index]

    def event_mask_set(self, *masks: str) -> None:
        """Record the requested facility mask."""
        self._check_open()
        self.event_masks = masks

    def event_callback_set(
        self, callback: Callable[[FakePulseEventInfo], None] | None
    ) -> None:
        """Register (or clear) the event callback."""
        self._check_open()
        self.event_callback = callback

    def event_listen(self) -> None:
        """Block until :meth:`event_listen_stop` is called.

        Real ``pulsectl.Pulse.event_listen`` blocks dispatching events
        to the registered callback until ``event_listener_running`` is
        cleared (typically via :meth:`pulsectl.Pulse.event_listen_stop`).
        Tests drive the callback synchronously via :meth:`emit_event`,
        so this method just parks the listener thread on an internal
        stop event. On entry the :attr:`event_listener_running` flag is
        set to ``True``; on exit it is left at whatever value the
        callback (or test) most recently wrote.
        """
        self._check_open()
        self.event_listener_running = True
        self._listen_release.wait()
        self._listen_release.clear()

    def event_listen_stop(self) -> None:
        """Release a thread parked in :meth:`event_listen`.

        Mirrors :meth:`pulsectl.Pulse.event_listen_stop`. The backend
        calls this from its teardown path so the event thread can
        return and be joined. Tests can also call this from the
        foreground after assertions are done.
        """
        self.event_listener_running = False
        self._listen_release.set()

    def emit_event(self, event_type: str, facility: str, index: int) -> None:
        """Synchronously deliver an event to the registered callback.

        Tests use this to simulate ``pulsectl`` events without standing
        up a real server. The callback runs on the calling thread, so
        side effects (additional ``module_load`` / ``module_unload``
        calls, ``event_listener_running = False`` toggles) take effect
        before this method returns.

        Raises:
            RuntimeError: Pulse has been closed.
        """
        self._check_open()
        self.event_calls.append((event_type, facility, index))
        if self.event_callback is not None:
            self.event_callback(
                FakePulseEventInfo(t=event_type, facility=facility, index=index)
            )

    def close(self) -> None:
        """Tear down the fake connection idempotently.

        Marks the instance closed, releases any thread parked in
        :meth:`event_listen`, and clears the registered callback.
        Subsequent calls into the pulse API raise ``RuntimeError``.
        """
        if self.closed:
            return
        self.closed = True
        self.event_listener_running = False
        self._listen_release.set()
        self.event_callback = None


class FakePulseRegistry:
    """Hand out a fresh :class:`FakePulse` on every ``open_pulse_control``
    call.

    :class:`FakePulse.close` flips ``closed=True`` irreversibly (it
    mirrors the real ``pulsectl.Pulse.close()`` contract that the
    PipeWire speaker tests assert against), so test code that drives a
    production path which opens *and* closes multiple control
    connections back-to-back -- as ``vrcpilot.mic.linux``'s
    ``register_virtual_mic`` + ``unregister_virtual_mic`` cycle does --
    cannot reuse a single fake.

    This registry produces a new :class:`FakePulse` per call, but
    preserves the in-memory PulseAudio model
    (``modules`` / ``next_module_id``) across calls so an
    ``unregister`` after a prior ``register`` still sees the
    null-sink the earlier connection loaded. The accumulated
    :attr:`module_load_calls` / :attr:`module_unload_calls` lists span
    every instance so assertions read the full scenario trace without
    caring how many control connections the production code opened.

    Usage::

        registry = FakePulseRegistry()
        mocker.patch.object(
            mic_linux, "open_pulse_control", side_effect=registry.open
        )

    Attributes:
        instances: Every :class:`FakePulse` handed out, in order.
        modules: Server-state snapshot kept in sync between opens.
        next_module_id: Monotonic counter shared across instances so
            re-opens never collide on a previously-assigned index.
    """

    def __init__(self) -> None:
        self.instances: list[FakePulse] = []
        self.modules: list[FakePulseModuleInfo] = []
        self.next_module_id: int = 0

    @property
    def module_load_calls(self) -> list[tuple[str, str]]:
        """Concatenated ``module_load`` trace across every handed-out
        instance."""
        return [call for inst in self.instances for call in inst.module_load_calls]

    @property
    def module_unload_calls(self) -> list[int]:
        """Concatenated ``module_unload`` trace across every handed-out
        instance."""
        return [idx for inst in self.instances for idx in inst.module_unload_calls]

    def open(self, client_name: str = "vrcpilot-mic") -> FakePulse:
        """Build a fresh :class:`FakePulse` wired to the shared server state.

        Each produced fake starts from the registry's persisted
        ``modules`` / ``next_module_id`` snapshot, then writes back
        through wrapped ``module_load`` / ``module_unload`` / ``close``
        so the next ``open()`` sees the most recent state -- including
        modules loaded by the previous instance.
        """
        pulse = FakePulse(client_name)
        pulse.modules = list(self.modules)
        pulse.next_module_id = self.next_module_id
        original_load = pulse.module_load
        original_unload = pulse.module_unload
        original_close = pulse.close

        def load(name: str, args: str) -> int:
            idx = original_load(name, args)
            self.modules = list(pulse.modules)
            self.next_module_id = pulse.next_module_id
            return idx

        def unload(index: int) -> None:
            original_unload(index)
            self.modules = list(pulse.modules)

        def close() -> None:
            self.modules = list(pulse.modules)
            self.next_module_id = pulse.next_module_id
            original_close()

        pulse.module_load = load  # pyright: ignore[reportAttributeAccessIssue]
        pulse.module_unload = unload  # pyright: ignore[reportAttributeAccessIssue]
        pulse.close = close  # pyright: ignore[reportAttributeAccessIssue]
        self.instances.append(pulse)
        return pulse


class _FakePwRecordStdout:
    """Stdout half of :class:`FakePwRecordProcess`.

    Models the subset of the :class:`io.RawIOBase` surface the speaker
    backend's drain thread uses: blocking :meth:`read` plus :meth:`close`.
    A :class:`threading.Condition` gates reads so the drain thread can
    park until the test pushes bytes via
    :meth:`FakePwRecordProcess.emit_pcm` or signals EOF via
    :meth:`FakePwRecordProcess.close_stdout`.
    """

    def __init__(self) -> None:
        self._buffer: bytearray = bytearray()
        self._cond: threading.Condition = threading.Condition()
        self._eof: bool = False
        self._closed: bool = False

    def read(self, n: int) -> bytes:
        """Block until ``n`` bytes are available, EOF, or close.

        Returns up to ``n`` bytes from the internal buffer; returns
        ``b""`` once EOF / close has been signalled and the buffer is
        drained.
        """
        if n <= 0:
            return b""
        with self._cond:
            while not self._buffer and not self._eof and not self._closed:
                self._cond.wait()
            if not self._buffer:
                return b""
            take = min(n, len(self._buffer))
            chunk = bytes(self._buffer[:take])
            del self._buffer[:take]
            return chunk

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def feed(self, data: bytes) -> None:
        with self._cond:
            self._buffer.extend(data)
            self._cond.notify_all()

    def signal_eof(self) -> None:
        with self._cond:
            self._eof = True
            self._cond.notify_all()


class FakePwRecordProcess:
    """Duck-typed stand-in for :class:`subprocess.Popen` of ``pw-record``.

    Mirrors the ``Popen`` slice the PipeWire speaker backend uses to
    drive its data plane: a blocking ``stdout.read`` drain, ``poll`` /
    ``wait`` lifecycle checks, ``terminate`` / ``kill`` shutdown, and a
    ``returncode`` attribute. ``stderr`` is exposed as ``None`` -- the
    backend captures it via :meth:`subprocess.Popen.communicate` only
    on failure paths the fake does not need to model.

    Args:
        args: The ``pw-record`` argv the production code would have
            spawned. Stored as :attr:`args` so tests can assert the
            CLI was constructed correctly.

    Attributes:
        args: Constructor argument, verbatim.
        stdout: A :class:`_FakePwRecordStdout` exposing ``read`` /
            ``close``. Test drivers push bytes through
            :meth:`emit_pcm` rather than touching this directly.
        stderr: ``None`` -- the backend never reads it on the happy
            path the fake covers.
        returncode: ``None`` while running, ``0`` after a graceful
            :meth:`terminate`, ``-9`` after :meth:`kill`.
        terminate_calls: Number of :meth:`terminate` invocations.
        kill_calls: Number of :meth:`kill` invocations.
        wait_calls: Number of :meth:`wait` invocations.
    """

    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.stdout = _FakePwRecordStdout()
        self.stderr: BinaryIO | None = None
        self.returncode: int | None = None
        self.terminate_calls: int = 0
        self.kill_calls: int = 0
        self.wait_calls: int = 0

    def emit_pcm(self, data: bytes) -> None:
        """Push raw PCM bytes into the stdout pipe.

        Wakes any drain thread parked in ``stdout.read``. After
        :meth:`terminate` or :meth:`close_stdout` further pushes are
        accepted but the consumer will see EOF before draining them;
        production code should not push after teardown anyway.
        """
        self.stdout.feed(data)

    def close_stdout(self) -> None:
        """Signal EOF on stdout.

        Subsequent ``stdout.read`` calls return ``b""`` once the
        already-buffered bytes are drained. Equivalent to ``pw-record``
        closing its output pipe.
        """
        self.stdout.signal_eof()

    def poll(self) -> int | None:
        """Return the process exit code, or ``None`` while running."""
        return self.returncode

    def terminate(self) -> None:
        """Graceful shutdown: set ``returncode=0`` and EOF stdout."""
        self.terminate_calls += 1
        if self.returncode is None:
            self.returncode = 0
        self.stdout.signal_eof()

    def kill(self) -> None:
        """Forceful shutdown: set ``returncode=-9`` and EOF stdout."""
        self.kill_calls += 1
        if self.returncode is None:
            self.returncode = -9
        self.stdout.signal_eof()

    def wait(self, timeout: float | None = None) -> int:
        """Return the exit code, defaulting to ``0`` if still running.

        The fake never actually blocks: tests are expected to call
        :meth:`terminate` (or :meth:`kill`) before :meth:`wait`. If
        neither has run yet, ``returncode`` is synthesised as ``0`` so
        the call still returns deterministically.
        """
        del timeout
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = 0
            self.stdout.signal_eof()
        return self.returncode


class FakeSpeaker:
    """Stand-in for :class:`vrcpilot.speaker.session.Speaker`.

    Used in :class:`vrcpilot.speaker.loop.SpeakerLoop` tests where the
    OS-level proc-tap backend is irrelevant but the loop's own threading
    machinery still needs to be exercised against a real, deterministic
    chunk source.

    Constructor arguments mirror :class:`vrcpilot.Speaker` so the fake
    can be substituted via either ``mocker.patch(..., FakeSpeaker)``
    (replace the class) or ``mocker.patch(..., return_value=fake)``
    (replace the instance).

    Args:
        read_timeout: Accepted for signature compatibility; recorded as
            :attr:`read_timeout` so tests can assert forwarding.
        read_side_effect: Raised from :meth:`read` instead of returning
            a chunk. ``None`` (default) returns a zero-length chunk.
        read_delay: Sleep injected before each :meth:`read` returns,
            useful for pacing tests.
        chunk: ndarray returned from :meth:`read`. Default is an empty
            ``(0, CHANNELS)`` array so tests can assert empty-chunk
            forwarding without setting anything up.
    """

    def __init__(
        self,
        *,
        read_timeout: float = 2.0,
        read_side_effect: BaseException | None = None,
        read_delay: float = 0.0,
        chunk: NDArray[np.float32] | None = None,
    ) -> None:
        self.read_timeout = read_timeout
        self.read_calls: int = 0
        self.close_calls: int = 0
        self._read_side_effect = read_side_effect
        self._read_delay = read_delay
        self._chunk = (
            chunk if chunk is not None else np.zeros((0, CHANNELS), dtype=np.float32)
        )

    def read(self) -> NDArray[np.float32]:
        self.read_calls += 1
        if self._read_delay > 0:
            time.sleep(self._read_delay)
        if self._read_side_effect is not None:
            raise self._read_side_effect
        return self._chunk

    def close(self) -> None:
        self.close_calls += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()


class FakeSpeakerLoop:
    """Stand-in for :class:`vrcpilot.speaker.SpeakerLoop`.

    Replaces the real loop in CLI tests where exercising the worker
    thread is not the point. ``start()`` synchronously emits a fixed
    number of chunks into the user callback so end-to-end behaviour
    of consumers (sinks, signal handlers) can still be verified.

    Class-level state (:attr:`instances` / :attr:`frames_per_start` /
    :attr:`samples_per_frame` / :attr:`init_side_effect`) is mutable
    so tests can configure behaviour before construction. Reset
    between tests by the ``record_fakes``-style fixture in your local
    conftest.
    """

    instances: list[FakeSpeakerLoop] = []
    frames_per_start: int = 3
    samples_per_frame: int = 1024
    init_side_effect: BaseException | None = None

    def __init__(
        self,
        callback: Callable[[NDArray[np.float32]], None],
        *,
        chunk_seconds: float = 0.05,
        read_timeout: float = 2.0,
    ) -> None:
        if FakeSpeakerLoop.init_side_effect is not None:
            raise FakeSpeakerLoop.init_side_effect
        self.callback = callback
        self.chunk_seconds = chunk_seconds
        self.read_timeout = read_timeout
        self.start_calls = 0
        FakeSpeakerLoop.instances.append(self)

    def start(self) -> None:
        self.start_calls += 1
        chunk = np.zeros(
            (FakeSpeakerLoop.samples_per_frame, CHANNELS), dtype=np.float32
        )
        for _ in range(FakeSpeakerLoop.frames_per_start):
            self.callback(chunk)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb


class FakeWavSink:
    """Stand-in for :class:`vrcpilot.speaker.WavFileSink`.

    Captures every written chunk in :attr:`writes` so CLI / loop
    integration tests can assert what would have been encoded without
    invoking the stdlib :mod:`wave` writer (which also keeps tests
    free of filesystem side effects).
    """

    instances: list[FakeWavSink] = []

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.writes: list[NDArray[np.float32]] = []
        self.closed = False
        FakeWavSink.instances.append(self)

    @property
    def sample_count(self) -> int:
        return sum(chunk.shape[0] for chunk in self.writes)

    def write(self, frame: NDArray[np.float32]) -> None:
        self.writes.append(frame)

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()


class FakeRawPcmStdoutSink:
    """Stand-in for :class:`vrcpilot.speaker.RawPcmStdoutSink`.

    Captures every written chunk in :attr:`writes` so CLI / loop
    integration tests can assert what would have been streamed to
    stdout without actually emitting s16le bytes.
    """

    instances: list[FakeRawPcmStdoutSink] = []

    def __init__(self, *, stream: BinaryIO | None = None) -> None:
        self.stream = stream
        self.writes: list[NDArray[np.float32]] = []
        self.closed = False
        FakeRawPcmStdoutSink.instances.append(self)

    @property
    def sample_count(self) -> int:
        return sum(chunk.shape[0] for chunk in self.writes)

    def write(self, frame: NDArray[np.float32]) -> None:
        self.writes.append(frame)

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()


class FakeOutputStream:
    """Stand-in for :class:`sounddevice.OutputStream`.

    Models the explicit-lifecycle surface
    :class:`vrcpilot.mic.Mic` drives directly: ``start`` is called from
    the Mic constructor, ``write`` from each :meth:`Mic.play`, and
    ``stop`` / ``close`` from :meth:`Mic.close`. Lifecycle flags
    (:attr:`started`, :attr:`stopped`, :attr:`closed`) let tests assert
    the ordering without simulating threading.
    """

    def __init__(
        self,
        *,
        samplerate: int,
        channels: int,
        dtype: str,
        device: int,
    ) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.device = device
        self.writes: list[NDArray[np.float32]] = []
        self.started: bool = False
        self.stopped: bool = False
        self.closed: bool = False

    def start(self) -> None:
        self.started = True

    def write(self, frame: NDArray[np.float32]) -> None:
        if self.closed:
            raise RuntimeError("write after close")
        self.writes.append(frame)

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class FakeSoundDevice:
    """Module-shaped stand-in for the ``sounddevice`` package.

    Tests install an instance via ``mocker.patch.dict(sys.modules,
    {"sounddevice": fake})`` so the lazy ``import sounddevice as sd``
    inside :mod:`vrcpilot.mic.devices` and :mod:`vrcpilot.mic.session`
    resolves to this fake instead of the real PortAudio binding. Only
    the surface the mic module actually touches is modelled here;
    widen the stand-in when new sounddevice calls are added in
    production.

    Currently models:

    * :meth:`query_devices` -- backs
      :func:`vrcpilot.mic.devices.lookup_output_device`.
    * :meth:`OutputStream` -- backs :meth:`vrcpilot.mic.Mic.play`.
      Each call records a :class:`FakeOutputStream` in
      :attr:`output_streams` so tests can assert constructor kwargs
      and written frames.
    """

    def __init__(self) -> None:
        self.devices: list[dict[str, Any]] = []
        self.output_streams: list[FakeOutputStream] = []

    def add_output_device(self, name: str, *, max_output_channels: int = 2) -> None:
        """Register an output-capable device.

        ``query_devices`` returns the registered entries in insertion
        order; the index a test passes to assertions matches the order
        of :meth:`add_output_device` / :meth:`add_input_device` calls.
        """
        self.devices.append(
            {
                "name": name,
                "max_output_channels": max_output_channels,
                "max_input_channels": 0,
            }
        )

    def add_input_device(self, name: str, *, max_input_channels: int = 2) -> None:
        """Register an input-only device (``max_output_channels=0``).

        Useful for asserting that output-device lookup skips input-only
        entries that happen to share a substring with the search needle.
        """
        self.devices.append(
            {
                "name": name,
                "max_input_channels": max_input_channels,
                "max_output_channels": 0,
            }
        )

    def query_devices(self) -> list[dict[str, Any]]:
        """Return a shallow copy of the registered device list."""
        return list(self.devices)

    def OutputStream(  # noqa: N802 -- mirrors sounddevice.OutputStream
        self,
        *,
        samplerate: int,
        channels: int,
        dtype: str,
        device: int,
    ) -> FakeOutputStream:
        """Return a fresh :class:`FakeOutputStream` and track it."""
        stream = FakeOutputStream(
            samplerate=samplerate,
            channels=channels,
            dtype=dtype,
            device=device,
        )
        self.output_streams.append(stream)
        return stream


class FakeMic:
    """Stand-in for :class:`vrcpilot.mic.Mic` for CLI tests.

    Mirrors the constructor-opens-stream / single-chunk-play /
    explicit-close lifecycle so CLI integration tests can assert that
    the right format was chosen, each chunk was forwarded, and the
    session was released on the way out. Construction never raises;
    the CLI's device-not-found path is exercised by patching ``Mic``
    to raise on instantiation instead.
    """

    instances: list[FakeMic] = []

    def __init__(
        self,
        device: str | None = None,
        *,
        sample_rate: int = 48000,
        channels: int = 1,
    ) -> None:
        self.device_argument = device
        self._sample_rate = sample_rate
        self._channels = channels
        self.played: list[NDArray[np.float32]] = []
        self.closed: bool = False
        FakeMic.instances.append(self)

    @property
    def device_name(self) -> str:
        return self.device_argument or "fake-device"

    @property
    def device_index(self) -> int:
        return 0

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def play(self, chunk: NDArray[np.float32]) -> None:
        if self.closed:
            raise RuntimeError("Mic is closed")
        self.played.append(chunk)

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()
