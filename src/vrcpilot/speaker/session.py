"""Public :class:`Speaker` session and platform dispatch.

Linux selects :class:`vrcpilot.speaker.linux.PipeWireSpeakerBackend`
(native PipeWire pipeline) and Windows selects
:class:`vrcpilot.speaker.windows.ProcTapSpeakerBackend` (``proc-tap``
process loopback). Both are imported lazily so the other platform's
optional dependency is never required. Every other platform raises
:class:`NotImplementedError`.
"""

from __future__ import annotations

import sys
from types import TracebackType
from typing import Self

import numpy as np
from numpy.typing import NDArray

from vrcpilot.process import resolve_pid

from .base import SpeakerBackend


def _select_speaker_backend(
    *,
    read_timeout: float,
    pid: int,
) -> SpeakerBackend:
    """Return a started :class:`SpeakerBackend` for the host platform.

    Backend imports are intentionally inline so the platform-specific
    optional dependency (``pulsectl`` on Linux, ``proc-tap`` on Windows)
    is only loaded on the matching host. Both submodules raise
    ``ImportError`` at import time on the wrong platform, so a top-level
    import would crash collection on any cross-platform CI shard.
    """
    if sys.platform == "linux":
        from vrcpilot.speaker.linux import PipeWireSpeakerBackend

        return PipeWireSpeakerBackend(read_timeout=read_timeout, pid=pid)
    if sys.platform == "win32":
        from vrcpilot.speaker.windows import ProcTapSpeakerBackend

        return ProcTapSpeakerBackend(read_timeout=read_timeout, pid=pid)
    raise NotImplementedError(f"Speaker is not supported on {sys.platform}")


class Speaker:
    """Process-isolated audio capture session for VRChat.

    Only audio emitted by the bound VRChat PID is delivered to the
    caller; co-resident applications and other VRChat instances stay
    off the stream. VRChat must already be running when the constructor
    is called.

    Args:
        read_timeout: Seconds :meth:`read` waits on a quiet stream
            before returning an empty ndarray. Must be ``> 0``.
        pid: Target VRChat PID. Omit to let
            :func:`vrcpilot.process.resolve_pid` pick the sole running
            instance; pass explicitly to disambiguate when several
            VRChat processes coexist.

    Raises:
        RuntimeError: VRChat is not running, or the platform backend
            failed to open.
        ValueError: ``read_timeout`` is not strictly positive.
        VRChatMultipleInstancesError: ``pid`` omitted and multiple
            instances are running.
        NotImplementedError: Host platform is neither Linux nor Windows.
    """

    _backend: SpeakerBackend
    _closed: bool

    def __init__(
        self,
        *,
        read_timeout: float = 2.0,
        pid: int | None = None,
    ) -> None:
        if read_timeout <= 0:
            raise ValueError(f"read_timeout must be > 0 (got {read_timeout})")

        self._closed = False
        resolved = resolve_pid(pid)
        self._backend = _select_speaker_backend(read_timeout=read_timeout, pid=resolved)

    def read(self) -> NDArray[np.float32]:
        """Return every sample buffered since the previous read.

        Shape is ``(N, CHANNELS)``; an empty ``(0, CHANNELS)`` array is
        the documented "no new audio" tick rather than an error.

        Raises:
            RuntimeError: Session is closed or the backend reports a
                fatal error.
        """
        if self._closed:
            raise RuntimeError("Speaker is closed")
        return self._backend.read()

    def close(self) -> None:
        """Release the backend.

        Idempotent; backend cleanup failures
        surface as :class:`RuntimeWarning` from the backend itself.
        """
        if self._closed:
            return
        self._closed = True
        self._backend.close()

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
