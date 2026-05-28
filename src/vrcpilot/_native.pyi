"""Type stub for the private native extension ``vrcpilot._native``.

The compiled module is a single cdylib that exposes its namespaces as
submodule *attributes* (``process`` / ``window`` / ``capture`` /
``speaker``). Each is modelled here as a class-typed attribute so pyright
resolves calls such as ``_native.process.find_pids()`` against this stub
without importing the compiled module (kept out of pyright's reach so
``strict`` on ``./src`` stays clean).

Phase 0 ships the empty scaffold. Each workstream adds ``@staticmethod``
declarations to the relevant class as its native functions land; the
runtime submodule exposes the matching module-level function, so the
call syntax is identical under both the stub and the real module.
"""

class _ProcessModule:
    @staticmethod
    def find_pids() -> list[int]:
        """PIDs of every running VRChat process, newest first."""

class _WindowModule:
    @staticmethod
    def focus_window(pid: int, /) -> bool:
        """Bring the VRChat window owned by ``pid`` to the foreground."""

    @staticmethod
    def unfocus_window(pid: int, /) -> bool:
        """Send the VRChat window owned by ``pid`` to the z-order bottom."""

    @staticmethod
    def is_window_foreground(pid: int, /) -> bool:
        """Whether the VRChat window owned by ``pid`` owns the foreground."""

    @staticmethod
    def get_window_rect(pid: int, /) -> tuple[int, int, int, int] | None:
        """``(x, y, width, height)`` of the VRChat window, or ``None``."""

class _CaptureModule: ...
class _SpeakerModule: ...

process: _ProcessModule
window: _WindowModule
capture: _CaptureModule
speaker: _SpeakerModule
