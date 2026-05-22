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
) -> SpeakerBackend:
    """Return a started :class:`SpeakerBackend` for the host platform."""
    if sys.platform == "linux":
        from vrcpilot.speaker.linux import PipeWireSpeakerBackend

        return PipeWireSpeakerBackend(read_timeout=read_timeout)
    if sys.platform == "win32":
        from vrcpilot.speaker.windows import ProcTapSpeakerBackend

        return ProcTapSpeakerBackend(read_timeout=read_timeout)
    raise NotImplementedError(f"Speaker is not supported on {sys.platform}")


class Speaker:
    """Process-isolated audio capture session for VRChat.

    VRChat must already be running when the constructor is called.
    ``read_timeout`` is in seconds and bounds how long :meth:`read`
    waits on a quiet stream before returning an empty ndarray.

    Raises:
        RuntimeError: VRChat is not running, or the platform backend
            failed to open.
        ValueError: ``read_timeout`` is not strictly positive.
        NotImplementedError: Host platform is neither Linux nor Windows.
    """

    _backend: SpeakerBackend
    _closed: bool

    def __init__(
        self,
        *,
        read_timeout: float = 2.0,
    ) -> None:
        if read_timeout <= 0:
            raise ValueError(f"read_timeout must be > 0 (got {read_timeout})")

        self._closed = False
        self._backend = _select_speaker_backend(read_timeout=read_timeout)

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
