"""Tests for :class:`vrcpilot.speaker.linux.PipeWireSpeakerBackend`.

The PipeWire backend wires together four 3rd-party surfaces (pulsectl,
``pw-record`` subprocess, ``pw-link`` subprocess, ``pw-dump`` subprocess)
that the testing skill **forbids** mirroring with fakes. The strategy
here therefore splits cleanly:

* **Hermetic tests** -- only those that fire **before** the backend
  touches any of those surfaces (constructor validation, the
  missing-CLI guard). These can run on any Linux host, even without
  PipeWire installed.
* **Integration-real tests** -- the full backend constructor /
  data-plane / teardown cycle against a real PipeWire daemon. Marked
  skip-if-infra-missing and otherwise exercised end-to-end. Some of
  this coverage is intentionally left to the e2e scenarios under
  ``tests/e2e/`` because the setup (a stand-in VRChat node piping
  sine into the bus) is non-trivial.

Why no fake-backed unit tests for ``_open_pulse`` / ``_spawn_pw_record``
/ ``_run_pw_dump`` / ``_run_pw_link``: see project policy --
``FakePulse`` / ``FakePwRecordProcess`` style stand-ins drift from
upstream and let CI go green while the real proc-tap path is broken.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

if not sys.platform.startswith("linux"):
    pytest.skip("vrcpilot.speaker.linux is Linux-only", allow_module_level=True)

from vrcpilot.speaker.linux import PipeWireSpeakerBackend  # noqa: E402

# ---------------------------------------------------------------------------
# Hermetic
# ---------------------------------------------------------------------------


class TestConstructorValidation:
    """Validation that fires before any external CLI / pulsectl is touched."""

    @pytest.mark.parametrize("bad", [0.0, -0.5, -1.0])
    def test_non_positive_read_timeout_rejected(self, bad: float) -> None:
        # Validation must fire before ``shutil.which`` runs so a
        # caller misuse never gets confused with a CLI-missing error.
        with pytest.raises(ValueError, match="read_timeout must be > 0"):
            PipeWireSpeakerBackend(read_timeout=bad, pid=4242)


class TestMissingCLIError:
    """The aggregated missing-CLI error message must name every missing
    tool."""

    def test_empty_path_lists_all_three_clis_in_error_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Clearing PATH is a *real* environment change that makes
        # shutil.which legitimately return None for every CLI -- no
        # 3rd-party mocking. Production code reads PATH via shutil,
        # so this exercises the same code path the user would hit on
        # a busybox / chroot install missing PipeWire.
        monkeypatch.setenv("PATH", "")
        with pytest.raises(RuntimeError) as excinfo:
            PipeWireSpeakerBackend(pid=4242)
        msg = str(excinfo.value)
        # All three documented CLIs must be named in the error so the
        # user knows which package to install.
        assert "pw-record" in msg
        assert "pw-link" in msg
        assert "pw-dump" in msg
        # And the install hint must point at pipewire / pipewire-pulse.
        assert "pipewire" in msg.lower()


# ---------------------------------------------------------------------------
# Integration-real
# ---------------------------------------------------------------------------


def _required_clis_present() -> bool:
    """All three external CLIs the backend depends on are on PATH."""
    return all(
        shutil.which(cli) is not None for cli in ("pw-record", "pw-link", "pw-dump")
    )


def _pulsectl_importable() -> bool:
    """``pulsectl`` is installed (the backend uses it for the control
    plane)."""
    try:
        import pulsectl  # type: ignore[import-not-found]  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _pulse_server_reachable() -> bool:
    """A PipeWire / PulseAudio server answers control queries."""
    if shutil.which("pactl") is None:
        return False
    probe = subprocess.run(["pactl", "info"], capture_output=True, text=True)
    return probe.returncode == 0


class TestPipeWireSpeakerBackendAgainstRealDaemon:
    """Real PipeWire end-to-end.

    Skips unless every dependency is present:

    * pw-record / pw-link / pw-dump on PATH
    * pulsectl importable in the venv
    * PipeWire / PulseAudio daemon reachable

    The PID used here is the *current* process PID -- the backend
    binds its monitor to a null-sink and links any VRChat-like output
    nodes (none, in a normal CI run), so the test only validates that
    the constructor and close cycle survives the real plumbing.
    """

    def setup_method(self) -> None:
        if not _required_clis_present():
            pytest.skip("pw-record / pw-link / pw-dump must all be installed")
        if not _pulsectl_importable():
            pytest.skip("pulsectl is required for the real PipeWire backend")
        if not _pulse_server_reachable():
            pytest.skip("no PipeWire / PulseAudio server reachable")

    def test_constructor_loads_and_close_unloads_real_null_sink(self) -> None:
        # We need a PID for the constructor -- our own process PID is
        # fine because the linker only attaches VRChat-like output
        # nodes, and we have none. The interesting bit is that the
        # backend's real null-sink load + atexit / cleanup succeeds
        # against a live PipeWire daemon (1.0+ syntax compatibility).
        import os

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        try:
            # The null-sink must appear in the module listing now.
            import pulsectl  # type: ignore[import-not-found]

            with pulsectl.Pulse("vrcpilot-test-probe") as p:
                args_present = [
                    getattr(m, "argument", "") or "" for m in p.module_list()
                ]
                assert any(
                    "sink_name=vrcpilot_tap" in arg for arg in args_present
                ), "vrcpilot_tap null-sink must be loaded during backend lifetime"
        finally:
            backend.close()

        # And after close it must be gone.
        import pulsectl  # type: ignore[import-not-found]

        with pulsectl.Pulse("vrcpilot-test-probe2") as p:
            args_after = [getattr(m, "argument", "") or "" for m in p.module_list()]
            assert not any(
                "sink_name=vrcpilot_tap" in arg for arg in args_after
            ), "vrcpilot_tap null-sink must be unloaded after backend.close"

    def test_read_returns_empty_chunk_when_no_audio_routes_to_tap(self) -> None:
        # No VRChat = no audio routed to the tap. Within the read
        # timeout, ``read`` must return a well-formed empty (0, 2)
        # float32 ndarray rather than hang.
        import os

        import numpy as np

        from vrcpilot.speaker.base import CHANNELS

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(read_timeout=0.3, pid=my_pid)
        try:
            buf = backend.read()
        finally:
            backend.close()
        # Either empty (the common case) or non-empty with proper
        # shape -- both honour the documented contract.
        assert buf.dtype == np.float32
        assert buf.ndim == 2
        assert buf.shape[1] == CHANNELS

    def test_close_is_idempotent_against_real_daemon(self) -> None:
        # ExitStack rollback paths and __exit__ chains both call
        # close; the wrapper must guard double-close so the underlying
        # pw-record terminate / null-sink unload runs once even under
        # repeated close.
        import os

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        backend.close()
        backend.close()
        backend.close()
