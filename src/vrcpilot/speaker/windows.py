"""Windows process-loopback backend backed by ``proc-tap``.

Thin adapter: ``proc-tap`` owns the COM plumbing
(``ActivateAudioInterfaceAsync`` + Process Loopback) and emits raw
float32/48k/stereo PCM, matching :mod:`vrcpilot.speaker.base` exactly
so no resampling or format negotiation is needed here.
"""

from __future__ import annotations

import sys

if sys.platform != "win32":
    raise ImportError("vrcpilot.speaker.windows is Windows-only")

import logging
import threading
import warnings
from typing import Any, override

import numpy as np
from numpy.typing import NDArray

from .base import CHANNELS, SpeakerBackend

_logger = logging.getLogger(__name__)


class ProcTapSpeakerBackend(SpeakerBackend):
    """SpeakerBackend backed by :class:`proctap.ProcessAudioCapture`.

    proc-tap binds Windows Process Loopback to a single PID so the
    captured stream contains only the bound process's audio; the
    backend trusts the caller's PID without re-resolving so it stays
    drivable from tests and from harnesses that already chose a PID.

    Args:
        read_timeout: Seconds :meth:`read` waits for the first chunk
            before returning empty. Must be ``> 0``.
        pid: Target VRChat PID. Pre-resolved by the caller (typically
            :class:`vrcpilot.speaker.Speaker`).

    Raises:
        ValueError: ``read_timeout`` is not strictly positive.
    """

    _pid: int
    _read_timeout: float
    _capture: Any
    _closed: bool
    _lock: threading.Lock

    def __init__(
        self,
        *,
        read_timeout: float = 2.0,
        pid: int,
    ) -> None:
        if read_timeout <= 0:
            raise ValueError(f"read_timeout must be > 0 (got {read_timeout})")

        self._pid = pid
        self._read_timeout = read_timeout
        self._closed = False
        self._lock = threading.Lock()
        self._capture = self._open_capture(pid=pid)
        self._capture.start()  # pyright: ignore[reportUnknownMemberType]

    def _open_capture(self, *, pid: int) -> Any:
        """Construct the underlying ``proc-tap`` capture object.

        Test seam: substituted via :func:`mocker.patch.object` with a
        duck-typed fake exposing ``start`` / ``stop`` / ``close`` /
        ``read(timeout)``.
        """
        # ``proc-tap`` is Windows-only (``sys_platform == 'win32'`` in
        # pyproject.toml). This module's top-of-file guard makes the body
        # unreachable for pyright on Linux, so only the stub ignore is
        # needed for the upstream ``proc-tap`` package.
        from proctap import (  # pyright: ignore[reportMissingTypeStubs]
            ProcessAudioCapture,
        )

        return ProcessAudioCapture(pid=pid)

    @override
    def read(self) -> NDArray[np.float32]:
        with self._lock:
            if self._closed:
                raise RuntimeError("ProcTapSpeakerBackend is closed")
            capture = self._capture

        # proc-tap's read() returns exactly one queued chunk (10-20 ms
        # of audio) per call. If we returned just that, callers waking
        # up every chunk_seconds would drop everything that piled up
        # between drains. Instead: block up to ``read_timeout`` for
        # the first chunk to arrive, then non-blocking drain the rest
        # so a single ``read`` hand-off covers every sample buffered
        # since the previous call.
        raw_chunks: list[bytes] = []
        buf = capture.read(timeout=self._read_timeout)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        while buf:
            raw_chunks.append(buf)  # pyright: ignore[reportUnknownArgumentType]
            buf = capture.read(timeout=0.0)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]

        if not raw_chunks:
            return np.zeros((0, CHANNELS), dtype=np.float32)

        joined = b"".join(raw_chunks)
        flat = np.frombuffer(joined, dtype=np.float32)
        # proc-tap always emits interleaved stereo; guard the framing
        # invariant in case a future version returns a partial frame at
        # shutdown rather than silently corrupting the reshape.
        remainder = flat.size % CHANNELS
        if remainder:
            _logger.warning(
                "proc-tap returned %d float32 samples not divisible by %d "
                "channels; dropping %d trailing samples.",
                flat.size,
                CHANNELS,
                remainder,
            )
            flat = flat[: flat.size - remainder]
        return flat.reshape(-1, CHANNELS).copy()

    @override
    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            capture = self._capture

        if capture is None:
            return
        try:
            capture.stop()  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001 - report but don't re-raise
            warnings.warn(f"proc-tap stop failed: {exc}", stacklevel=2)
        try:
            capture.close()  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001 - report but don't re-raise
            warnings.warn(f"proc-tap close failed: {exc}", stacklevel=2)
