"""PID-scoped VRChat audio relay.

:class:`Router` couples :class:`vrcpilot.speaker.SpeakerLoop` (PID-scoped
capture on a worker thread) with a :mod:`soundcard` output player so the
audio of a single VRChat process is forwarded verbatim to a chosen
speaker. Cross-platform: ``soundcard`` handles the output side and
``Speaker`` handles per-PID capture, so this module has no Windows /
Linux split.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, ContextManager, Self

import numpy as np
from numpy.typing import NDArray

from vrcpilot.speaker import SpeakerLoop
from vrcpilot.speaker.base import CHANNELS, SAMPLE_RATE
from vrcpilot.speaker.routing.base import AudioDevice
from vrcpilot.speaker.routing.devices import default_device, find_device

# Aliases for the untyped ``soundcard`` surface. Keeping them named
# makes the intent clear at every consumption site and localises the
# ``# pyright: ignore`` clusters to the helper that creates the value.
_PlayerCtx = ContextManager[Any]
_Player = Any


def _resolve_device(device: str | AudioDevice | None) -> AudioDevice:
    if device is None:
        return default_device()
    if isinstance(device, AudioDevice):
        return device
    return find_device(device)


def _open_player(
    device: AudioDevice, blocksize: int | None
) -> tuple[_PlayerCtx, _Player]:
    """Resolve the ``soundcard`` speaker and enter its player context.

    Returns ``(context_manager, entered_player)``; caller is responsible
    for invoking ``context_manager.__exit__`` on cleanup.
    """
    import soundcard as sc  # pyright: ignore[reportMissingTypeStubs]

    sc_speaker: Any = sc.get_speaker(  # pyright: ignore[reportUnknownMemberType]
        device.id
    )
    ctx: _PlayerCtx = sc_speaker.player(  # pyright: ignore[reportUnknownMemberType]
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        blocksize=blocksize,
    )
    return ctx, ctx.__enter__()


class Router:
    """Relay one VRChat PID's audio to a chosen output device.

    Constructing the ``Router`` resolves ``device`` to an
    :class:`AudioDevice` but does *not* open any audio stream;
    :meth:`start` is what acquires resources. Use either the explicit
    ``start()`` / ``stop()`` pair, the :meth:`close` alias, or the
    context manager - all three are interchangeable.

    Lifecycle:
        :meth:`start` opens the output player first, then spawns the
        inner :class:`SpeakerLoop`. If the capture side fails, the
        already-opened player is rolled back before the original
        exception propagates so a partial start leaves no resource
        attached. :meth:`stop` tears both down: the worker stop call
        sits in ``try``, the player ``__exit__`` in ``finally``, so the
        player is always released even when the loop's worker thread
        re-raises a captured exception (e.g. VRChat died mid-relay).
        Double-``start()`` and double-``stop()`` are intentional no-ops
        (F2.3 / F2.5). After a successful ``stop()`` the instance is
        re-startable: a fresh ``SpeakerLoop`` and player pair are
        created on the next ``start()`` (F2.13), which is what makes
        re-entering the ``with`` block well-defined.

    Threading:
        ``start`` / ``stop`` are expected to be called from the main
        thread. :meth:`_on_frames` runs on the ``SpeakerLoop`` worker
        thread; it reads the player slot via a single snapshot so a
        callback racing with ``stop()`` simply sees ``None`` and skips
        without locking.

    Args:
        pid: Target VRChat PID. Forwarded to the inner ``SpeakerLoop``;
            ``None`` is *not* accepted here - multi-instance setups
            must name the PID explicitly.
        device: ``None`` to pick the OS default (resolved via
            :func:`default_device`), ``str`` to resolve through
            :func:`find_device`, or an :class:`AudioDevice` to use
            directly.
        chunk_seconds: Forwarded to ``SpeakerLoop`` (capture-side tick
            in seconds). Must be ``> 0``; validated by ``SpeakerLoop``
            at ``start()`` time, not at construction.
        blocksize: Forwarded to ``soundcard.Speaker.player`` (output
            buffer size in frames). ``None`` lets ``soundcard`` pick
            the backend default.
    """

    _pid: int
    _device: AudioDevice
    _chunk_seconds: float
    _blocksize: int | None
    _sc_player_ctx: _PlayerCtx | None
    _sc_player: _Player
    _loop: SpeakerLoop | None

    def __init__(
        self,
        pid: int,
        device: str | AudioDevice | None = None,
        *,
        chunk_seconds: float = 0.02,
        blocksize: int | None = None,
    ) -> None:
        self._pid = pid
        self._device = _resolve_device(device)
        self._chunk_seconds = chunk_seconds
        self._blocksize = blocksize
        self._sc_player_ctx = None
        self._sc_player = None
        self._loop = None

    @property
    def device(self) -> AudioDevice:
        """The :class:`AudioDevice` resolved at construction time."""
        return self._device

    @property
    def is_running(self) -> bool:
        """``True`` between ``start()`` and ``stop()``."""
        loop = self._loop
        return loop is not None and loop.is_running

    def start(self) -> None:
        """Open the output player and start the capture loop.

        Player is opened *before* the loop so the very first callback
        the worker thread fires already has a ready output stream. No-op
        when already running (F2.3). On capture-side failure the
        output player is rolled back before the exception propagates,
        leaving the instance in a clean stopped state.

        Raises:
            RuntimeError: ``SpeakerLoop`` / ``Speaker`` failed to start
                (e.g. VRChat process not running).
            ValueError: ``chunk_seconds <= 0`` (surfaced by
                ``SpeakerLoop.__init__``).
            OSError: ``soundcard`` failed to open the player (device
                disappeared between resolution and ``start()``,
                libpulse / WASAPI runtime error, etc.).
            NotImplementedError: Host is neither Windows nor Linux
                (surfaced by ``Speaker`` backend dispatch).
        """
        if self.is_running:
            return

        ctx, player = _open_player(self._device, self._blocksize)
        self._sc_player_ctx = ctx
        self._sc_player = player

        try:
            loop = SpeakerLoop(
                callback=self._on_frames,
                chunk_seconds=self._chunk_seconds,
                pid=self._pid,
            )
            loop.start()
        except BaseException:
            # Roll back the already-entered player so the partial start
            # leaves no resource attached.
            self._sc_player = None
            self._sc_player_ctx = None
            ctx.__exit__(None, None, None)
            raise

        self._loop = loop

    def stop(self) -> None:
        """Stop the capture loop, then close the output player.

        Order (F2.4 / §8.2): the ``SpeakerLoop.stop()`` call lives in a
        ``try`` block; the player ``__exit__`` lives in ``finally`` so
        it always runs. Any worker exception surfaced by
        ``SpeakerLoop.stop()`` (e.g. VRChat died mid-relay) is
        re-raised *after* the player is cleaned up.

        No-op when already stopped (F2.5). The internal slots are
        cleared up front so a callback firing concurrently with
        ``stop()`` sees a ``None`` player and skips its ``play()`` call
        instead of touching a half-closed stream. The ``SpeakerLoop``
        clears its captured exception after re-raising, so a second
        ``stop()`` following an exception-bearing first one runs
        cleanly (F2.12).
        """
        # Snapshot then clear up front so a callback firing concurrently
        # with stop() sees a ``None`` player and skips its play() call
        # (mirrors the _on_frames defensive read).
        loop = self._loop
        ctx = self._sc_player_ctx
        self._loop = None
        self._sc_player_ctx = None
        self._sc_player = None

        try:
            if loop is not None:
                loop.stop()
        finally:
            if ctx is not None:
                ctx.__exit__(None, None, None)

    def close(self) -> None:
        """Alias for :meth:`stop`."""
        self.stop()

    def __enter__(self) -> Self:
        """Call :meth:`start` and return ``self``."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Call :meth:`stop`; never swallow exceptions from the body.

        Returns ``None`` (not ``False``) so any in-flight exception
        keeps propagating, and a worker-thread exception re-raised by
        ``stop()`` itself replaces - rather than masks - the body's
        exception via the standard ``__exit__`` chaining rules.
        """
        del exc_type, exc_val, exc_tb
        self.stop()

    def _on_frames(self, frames: NDArray[np.float32]) -> None:
        """Forward ``frames`` to the output player.

        Empty frames (the ``SpeakerLoop`` silence-tick contract) are
        skipped. A ``None`` player snapshot - which can happen when
        ``stop()`` runs concurrently with a still-in-flight callback -
        is also skipped without error.
        """
        if frames.size == 0:
            return
        player = self._sc_player
        if player is None:
            return
        player.play(frames)  # pyright: ignore[reportUnknownMemberType]


def route(
    pid: int,
    device: str | AudioDevice | None = None,
    *,
    chunk_seconds: float = 0.02,
    blocksize: int | None = None,
) -> Router:
    """Construct and :meth:`Router.start` in one call.

    Convenience for the common case of "open a relay and let me hold
    the handle". The returned :class:`Router` is already running; the
    caller owns the lifecycle from here on (call :meth:`Router.stop`,
    :meth:`Router.close`, or use the ``with`` block). If
    :meth:`Router.start` raises, the exception propagates and no
    :class:`Router` is returned - there is nothing for the caller to
    clean up because ``start()`` rolled back the partial player itself.

    See :class:`Router` for the meaning of each argument.
    """
    router = Router(
        pid,
        device,
        chunk_seconds=chunk_seconds,
        blocksize=blocksize,
    )
    router.start()
    return router
