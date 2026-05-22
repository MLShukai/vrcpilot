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

* :class:`FakeSpeakerLoop` mirrors the CLI-facing
  :class:`vrcpilot.speaker.SpeakerLoop` so ``vrcpilot.cli.record``
  tests can run without proc-tap. Mirrors :mod:`tests.fakes.capture`
  1:1 (``instances`` class-level list, ``frames_per_start`` /
  ``init_side_effect`` knobs).

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
from types import TracebackType
from typing import BinaryIO, Self

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
