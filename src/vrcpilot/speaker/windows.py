"""Windows process-loopback backend backed by ``proc-tap``.

``proc-tap`` is a small Python package that ships a native extension
per platform and wraps the OS-specific process-loopback API; on
Windows it drives ``ActivateAudioInterfaceAsync`` + Process Loopback.
Linux uses :mod:`vrcpilot.speaker.linux` (native PipeWire) instead, so
this module is Windows-only.

We delegate the OS-specific COM plumbing to ``proc-tap`` and keep this
module to a thin adapter:

1. Resolve the VRChat PID via :func:`vrcpilot.process.find_pid`.
2. Construct a ``proctap.ProcessAudioCapture`` and start it.
3. Decode the ``bytes`` chunks proc-tap produces into ``(N, 2)``
   ``float32`` ndarrays so the rest of the speaker stack stays in
   the ndarray-of-float32 contract documented on
   :class:`vrcpilot.speaker.base.SpeakerBackend`.

The standard format proc-tap guarantees (48 kHz / stereo / float32)
matches the constants in :mod:`vrcpilot.speaker.base` exactly, so we
don't carry our own resampling or format negotiation.
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

from vrcpilot import process
from vrcpilot.speaker.base import CHANNELS, SpeakerBackend

_logger = logging.getLogger(__name__)


class ProcTapSpeakerBackend(SpeakerBackend):
    """SpeakerBackend backed by :class:`proctap.ProcessAudioCapture`.

    Windows-only. proc-tap is installed only on Windows (see the
    ``proc-tap`` environment marker in ``pyproject.toml``); the
    module-level guard above raises :class:`ImportError` on any other
    platform so this class is never reached off-Windows.

    Args:
        read_timeout: Per-:meth:`read` timeout forwarded to
            :meth:`proctap.ProcessAudioCapture.read`, in seconds.
            Quiet periods on the audio stream surface as an empty
            ``(0, CHANNELS)`` ndarray rather than an exception. Must
            be strictly positive.

    Raises:
        RuntimeError: VRChat is not running (``find_pid`` returned
            ``None``).
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
    ) -> None:
        if read_timeout <= 0:
            raise ValueError(f"read_timeout must be > 0 (got {read_timeout})")

        pid = process.find_pid()
        if pid is None:
            raise RuntimeError("VRChat is not running")

        self._pid = pid
        self._read_timeout = read_timeout
        self._closed = False
        self._lock = threading.Lock()
        self._capture = self._open_capture(pid=pid)
        self._capture.start()  # pyright: ignore[reportUnknownMemberType]

    def _open_capture(self, *, pid: int) -> Any:
        """Construct the underlying ``proc-tap`` capture object.

        This is the seam tests substitute via
        :func:`mocker.patch.object` to inject a duck-typed fake that
        exposes ``start`` / ``stop`` / ``close`` / ``read(timeout)`` --
        the same surface as :class:`proctap.ProcessAudioCapture`.
        """
        # ``proc-tap`` is a Windows-only conditional dependency
        # (``sys_platform == 'win32'`` in pyproject.toml); silence the
        # missing-import + missing-stub fallout when pyright runs on Linux.
        from proctap import (  # pyright: ignore[reportMissingTypeStubs, reportMissingImports]
            ProcessAudioCapture,  # pyright: ignore[reportUnknownVariableType]
        )

        return ProcessAudioCapture(pid=pid)  # pyright: ignore[reportUnknownVariableType]

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
