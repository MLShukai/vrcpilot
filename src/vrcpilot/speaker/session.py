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

from vrcpilot.speaker.base import SpeakerBackend


def _select_speaker_backend(
    *,
    read_timeout: float,
    pid: int,
) -> SpeakerBackend:
    """Return a started :class:`SpeakerBackend` for the host platform."""
    if sys.platform == "linux":
        from vrcpilot.speaker.linux import PipeWireSpeakerBackend

        return PipeWireSpeakerBackend(read_timeout=read_timeout, pid=pid)
    if sys.platform == "win32":
        from vrcpilot.speaker.windows import ProcTapSpeakerBackend

        return ProcTapSpeakerBackend(read_timeout=read_timeout, pid=pid)
    raise NotImplementedError(f"Speaker is not supported on {sys.platform}")


class Speaker:
    """Process-isolated audio capture session for VRChat.

    VRChat must already be running when the constructor is called.
    ``read_timeout`` is in seconds and bounds how long :meth:`read`
    waits on a quiet stream before returning an empty ndarray.

    Args:
        read_timeout: Seconds :meth:`read` waits for new samples before
            returning an empty ndarray. Must be ``> 0``. Default ``2.0``.
        pid: Target VRChat PID. When omitted,
            :func:`vrcpilot.process.resolve_pid` picks the sole running
            instance and raises
            :class:`vrcpilot.process.VRChatMultipleInstancesError` if more
            than one VRChat process is running. Pass an explicit PID to
            bind the speaker session to one instance when several are
            running concurrently.

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

        # Import lazily so the dispatch test can stub
        # ``vrcpilot.speaker.session._select_speaker_backend`` without
        # also having to satisfy ``resolve_pid``'s real implementation.
        from vrcpilot.process import resolve_pid

        self._closed = False
        resolved = resolve_pid(pid)
        self._backend = _select_speaker_backend(read_timeout=read_timeout, pid=resolved)

    def read(self) -> NDArray[np.float32]:
        """Return every sample buffered since the previous read.

        Shape ``(N, CHANNELS)``; ``N == 0`` is the valid "no new audio"
        signal, returned when no samples arrive within ``read_timeout``.

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
