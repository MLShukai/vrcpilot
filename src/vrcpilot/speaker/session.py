"""Public :class:`Speaker` session and backend selection.

Thin context-manager wrapper around a :class:`SpeakerBackend`,
mirroring :class:`vrcpilot.capture.Capture`. The wrapper owns the
closed-state flag so backend implementations only have to honour the
ABC contract.

Strict two-way platform dispatch: Linux uses
:class:`vrcpilot.speaker.linux.PipeWireSpeakerBackend` (native PipeWire
CLIs + ``pulsectl`` control plane) and Windows uses
:class:`vrcpilot.speaker.windows.ProcTapSpeakerBackend` (process
loopback via the ``proc-tap`` package, which is Windows-only here).
Every other platform raises :class:`NotImplementedError` at dispatch
time. Both backends are imported lazily so a missing optional
dependency on one platform never breaks ``import vrcpilot.speaker``
on the other.
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
    """Return a started :class:`SpeakerBackend` for the host platform.

    Imports the chosen backend lazily so platform-specific dependencies
    (``proc-tap`` on Windows, ``pulsectl`` and the PipeWire CLIs on
    Linux) never need to be importable on the other platform. Linux
    selects :class:`PipeWireSpeakerBackend`, Windows selects
    :class:`ProcTapSpeakerBackend`, and every other platform raises
    :class:`NotImplementedError` -- there is no fall-through path.
    """
    if sys.platform == "linux":
        from vrcpilot.speaker.linux import PipeWireSpeakerBackend

        return PipeWireSpeakerBackend(read_timeout=read_timeout)
    if sys.platform == "win32":
        from vrcpilot.speaker.windows import ProcTapSpeakerBackend

        return ProcTapSpeakerBackend(read_timeout=read_timeout)
    raise NotImplementedError(f"Speaker is not supported on {sys.platform}")


class Speaker:
    """Process-isolated audio capture session for VRChat.

    VRChat must already be running when the constructor is called; the
    backend resolves the target PID via :func:`vrcpilot.process.find_pid`
    and raises :class:`RuntimeError` otherwise. The session is
    single-use: one backend connection is held open until :meth:`close`,
    and each :meth:`read` returns every sample buffered since the
    previous call.

    ``read_timeout`` is in seconds and must be strictly positive -- it
    bounds how long :meth:`read` blocks on a quiet stream before
    returning an empty ndarray.

    Raises:
        RuntimeError: Backend cannot start (VRChat is not running, or
            the underlying platform-specific capture failed to open).
        ValueError: ``read_timeout`` is not strictly positive.
        NotImplementedError: The host platform is neither Linux nor
            Windows.
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
        """Return every sample accumulated since the previous read.

        Shape ``(N, CHANNELS)``, dtype ``float32``, sample rate
        ``SAMPLE_RATE`` Hz. ``N == 0`` is a valid "no new audio" signal
        and is returned when the backend's underlying event does not
        fire within ``read_timeout`` seconds.

        Raises:
            RuntimeError: The session has been closed, or the backend
                reports a fatal error.
        """
        if self._closed:
            raise RuntimeError("Speaker is closed")
        return self._backend.read()

    def close(self) -> None:
        """Release the backend; idempotent and never raises.

        Backend cleanup failures inside :meth:`SpeakerBackend.close`
        are the backend's contract to surface (typically as
        :class:`RuntimeWarning`); the wrapper just flips ``_closed``
        and forwards once.
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
