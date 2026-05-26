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

    Lifecycle:
        ``start()`` opens the output player first, then spawns the inner
        :class:`SpeakerLoop`; on capture-side failure the player is
        rolled back before the original exception propagates. ``stop()``
        tears down both even if the loop's worker raised - the player
        cleanup runs in ``finally``, the worker exception is re-raised
        after. The instance is re-startable: ``stop()`` followed by
        ``start()`` builds a fresh ``SpeakerLoop`` / player pair.

    Args:
        pid: Target VRChat PID. Forwarded to the inner ``SpeakerLoop``.
        device: ``None`` to pick the OS default, ``str`` for
            :func:`find_device` lookup, or an :class:`AudioDevice` to
            use directly.
        chunk_seconds: Forwarded to ``SpeakerLoop``; must be ``> 0``
            (validated downstream).
        blocksize: Forwarded to ``soundcard.Speaker.player`` (output
            buffer size in frames). ``None`` lets ``soundcard`` choose.
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

        No-op when already running (F2.3). On capture-side failure the
        output player is cleaned up before the exception propagates.

        Raises:
            RuntimeError: ``SpeakerLoop`` / ``Speaker`` failed to start
                (e.g. VRChat not running).
            ValueError: ``chunk_seconds <= 0``.
            OSError: ``soundcard`` failed to open the player.
            NotImplementedError: Host is neither Windows nor Linux.
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
        ``SpeakerLoop.stop()`` is re-raised *after* the player is
        cleaned up.

        No-op when already stopped (F2.5). The ``SpeakerLoop`` clears
        its captured exception after re-raising, so a second ``stop()``
        following an exception-bearing first one runs cleanly (F2.12).
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
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
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
    """Construct and ``start()`` a :class:`Router`.

    Caller owns the lifecycle (``stop()`` / ``close()`` / ``with``).
    Any exception from ``Router.start()`` propagates; no router is
    returned in that case.
    """
    router = Router(
        pid,
        device,
        chunk_seconds=chunk_seconds,
        blocksize=blocksize,
    )
    router.start()
    return router
