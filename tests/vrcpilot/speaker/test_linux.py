"""Tests for :class:`vrcpilot.speaker.linux.PipeWireSpeakerBackend`.

The PipeWire backend wires together three 3rd-party surfaces (pulsectl,
``pw-record`` subprocess, ``psutil``) that the testing skill **forbids**
mirroring with fakes. The strategy here therefore splits cleanly:

* **Hermetic tests** -- those that fire **before** the backend touches
  any of those surfaces (constructor validation, the missing-CLI guard,
  pure-helper math). These can run on any Linux host, even without
  PipeWire installed.
* **Integration-real tests** -- the full backend constructor /
  data-plane / teardown cycle against a real PipeWire daemon. Marked
  skip-if-infra-missing and otherwise exercised end-to-end. Some
  coverage is intentionally left to the e2e scenarios under
  ``tests/e2e/`` because the setup (a stand-in VRChat node piping
  sine into the bus) is non-trivial.

Why no fake-backed unit tests for the pulsectl / subprocess seams: see
project policy -- ``FakePulse`` / ``FakePwRecordProcess`` style
stand-ins drift from upstream and let CI go green while the real
PipeWire path is broken.
"""

from __future__ import annotations

import shutil
import sys

import pytest

if not sys.platform.startswith("linux"):
    pytest.skip("vrcpilot.speaker.linux is Linux-only", allow_module_level=True)

from tests.helpers import has_pipewire  # noqa: E402
from vrcpilot.speaker.linux import (  # noqa: E402
    _REQUIRED_CLIS,
    PipeWireSpeakerBackend,
    _extract_tap_pid,
    _loopback_args,
    _null_sink_args,
    _pw_record_argv,
    _tap_sink_name,
)

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
    """The aggregated missing-CLI error message must name every required
    tool."""

    def test_empty_path_lists_required_cli_in_error_message(
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
        # Every declared required CLI must be named in the error so
        # the user knows exactly what is missing.
        for cli in _REQUIRED_CLIS:
            assert cli in msg, f"{cli} should be named in error: {msg}"
        # And the install hint must point at pipewire / pipewire-pulse.
        assert "pipewire" in msg.lower()


class TestHelperFunctions:
    """Pure-function helpers — no PipeWire / pulsectl required."""

    @pytest.mark.parametrize(
        "pid,expected",
        [
            (1234, "vrcpilot_tap_1234"),
            (1, "vrcpilot_tap_1"),
            (99999999, "vrcpilot_tap_99999999"),
        ],
    )
    def test_tap_sink_name_embeds_pid(self, pid: int, expected: str) -> None:
        assert _tap_sink_name(pid) == expected

    def test_null_sink_args_uses_per_pid_name_and_audio_format(self) -> None:
        args = _null_sink_args(4242)
        assert "sink_name=vrcpilot_tap_4242" in args
        assert "device.description=VRCPilotTap_4242" in args
        assert "rate=48000" in args
        assert "channels=2" in args
        assert "format=float32le" in args

    def test_loopback_args_targets_per_pid_monitor_and_default_sink(
        self,
    ) -> None:
        args = _loopback_args(4242, "alsa_output.user_default")
        assert "source=vrcpilot_tap_4242.monitor" in args
        assert "sink=alsa_output.user_default" in args
        assert "source_dont_move=true" in args
        assert "sink_dont_move=true" in args
        assert "latency_msec=20" in args

    def test_pw_record_argv_targets_per_pid_monitor(self) -> None:
        argv = _pw_record_argv(4242)
        assert argv[0] == "pw-record"
        assert any(a == "--target=vrcpilot_tap_4242.monitor" for a in argv)
        assert "--format=f32" in argv
        assert "--rate=48000" in argv
        assert "--channels=2" in argv

    @pytest.mark.parametrize(
        "module_name,argument,expected",
        [
            (
                "module-null-sink",
                "sink_name=vrcpilot_tap_1234 channels=2",
                1234,
            ),
            # Trailing-position match: PulseAudio appends a trailing
            # space-equivalent so the regex can anchor on the boundary
            # even at end-of-string.
            (
                "module-null-sink",
                "channels=2 sink_name=vrcpilot_tap_42",
                42,
            ),
            (
                "module-loopback",
                "source=vrcpilot_tap_88.monitor sink=foo",
                88,
            ),
            # Adjacent-PID disambiguation: 1234 must not match 12345.
            (
                "module-null-sink",
                "sink_name=vrcpilot_tap_12345 channels=2",
                12345,
            ),
            # Unrelated modules are ignored.
            ("module-stream-restore", "anything", None),
            # Loopback regex doesn't match a null-sink-style argument
            # (the source/sink-name distinction prevents cross-matches).
            (
                "module-loopback",
                "sink_name=vrcpilot_tap_1234 channels=2",
                None,
            ),
            # Other suffixes are not ours.
            ("module-null-sink", "sink_name=VRCPilotMic channels=2", None),
            # Missing argument / module_name.
            ("module-null-sink", None, None),
            (None, "sink_name=vrcpilot_tap_1234", None),
        ],
    )
    def test_extract_tap_pid_boundaries(
        self, module_name: str | None, argument: str | None, expected: int | None
    ) -> None:
        assert _extract_tap_pid(module_name, argument) == expected


# ---------------------------------------------------------------------------
# Integration-real
# ---------------------------------------------------------------------------


def _required_clis_present() -> bool:
    """Every external CLI the backend depends on is on PATH."""
    return all(shutil.which(cli) is not None for cli in _REQUIRED_CLIS)


def _pulsectl_importable() -> bool:
    """``pulsectl`` is installed (the backend uses it for the control
    plane)."""
    try:
        import pulsectl  # type: ignore[import-not-found]  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


class TestPipeWireSpeakerBackendAgainstRealDaemon:
    """Real PipeWire end-to-end.

    Skips unless every dependency is present:

    * every CLI listed in ``_REQUIRED_CLIS`` on PATH
    * pulsectl importable in the venv
    * PipeWire daemon reachable (probed via ``has_pipewire`` /
      ``pw-cli info 0``)

    The PID used here is the *current* process PID -- the backend
    creates a per-pid null-sink + loopback and moves any VRChat-like
    sink_inputs onto the tap (none, in a normal CI run), so the test
    only validates that the constructor and close cycle survive the
    real plumbing.
    """

    def setup_method(self) -> None:
        if not _required_clis_present():
            pytest.skip(f"required CLIs must all be installed: {_REQUIRED_CLIS}")
        if not _pulsectl_importable():
            pytest.skip("pulsectl is required for the real PipeWire backend")
        if not has_pipewire():
            pytest.skip("no PipeWire daemon reachable")

    def test_constructor_loads_and_close_unloads_real_null_sink(self) -> None:
        # We need a PID for the constructor -- our own process PID is
        # fine because the move-streams step only touches VRChat-like
        # sink_inputs, and we have none. The interesting bit is that
        # the backend's real null-sink + loopback load + atexit
        # cleanup succeeds against a live PipeWire daemon (1.0+
        # syntax compatibility).
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

    def test_loopback_is_loaded_for_current_pid(self) -> None:
        """The loopback bridging tap.monitor → default sink must exist during
        the backend's lifetime and disappear at close."""
        import os

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        try:
            import pulsectl  # type: ignore[import-not-found]

            target = f"source=vrcpilot_tap_{my_pid}.monitor"
            with pulsectl.Pulse("vrcpilot-test-probe-lb") as p:
                modules = list(p.module_list())
                loopback_args = [
                    getattr(m, "argument", "") or ""
                    for m in modules
                    if getattr(m, "name", None) == "module-loopback"
                ]
                assert any(target in arg for arg in loopback_args), (
                    f"module-loopback for {target} must be loaded during "
                    f"backend lifetime; saw {loopback_args}"
                )
        finally:
            backend.close()

        with pulsectl.Pulse("vrcpilot-test-probe-lb2") as p:
            modules_after = list(p.module_list())
            args_after = [
                getattr(m, "argument", "") or ""
                for m in modules_after
                if getattr(m, "name", None) == "module-loopback"
            ]
            assert not any(
                f"source=vrcpilot_tap_{my_pid}.monitor" in arg for arg in args_after
            ), "module-loopback must be unloaded after backend.close"

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
        # pw-record terminate / null-sink unload / loopback unload
        # runs once even under repeated close.
        import os

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        backend.close()
        backend.close()
        backend.close()

    def test_two_backends_have_independent_per_pid_taps(self) -> None:
        """Two backends with distinct PIDs each own a private sink + loopback
        and neither close path tramples the other's modules."""
        import os

        import pulsectl  # type: ignore[import-not-found]

        real_pid = os.getpid()
        # The second PID needs to look "live" to the stale-tap sweep so
        # it isn't unloaded on creation. A second psutil-visible process
        # works: pick the init / launcher process (pid=1) which is
        # guaranteed to exist on any Linux host. There are no VRChat
        # sink_inputs for pid=1, so the backend just sets up its tap
        # and stays idle.
        ghost_pid = 1
        backend_real = PipeWireSpeakerBackend(pid=real_pid)
        try:
            backend_ghost = PipeWireSpeakerBackend(pid=ghost_pid)
            try:
                with pulsectl.Pulse("vrcpilot-test-probe-2x") as p:
                    sinks = [getattr(s, "name", "") for s in p.sink_list()]
                    assert f"vrcpilot_tap_{real_pid}" in sinks
                    assert f"vrcpilot_tap_{ghost_pid}" in sinks
            finally:
                backend_ghost.close()

            # backend_ghost.close() must leave backend_real's sink alive.
            with pulsectl.Pulse("vrcpilot-test-probe-2x-after") as p:
                sinks_after_ghost = [getattr(s, "name", "") for s in p.sink_list()]
                assert f"vrcpilot_tap_{real_pid}" in sinks_after_ghost
                assert f"vrcpilot_tap_{ghost_pid}" not in sinks_after_ghost
        finally:
            backend_real.close()

        # And both are gone after the outer close.
        with pulsectl.Pulse("vrcpilot-test-probe-2x-final") as p:
            sinks_final = [getattr(s, "name", "") for s in p.sink_list()]
            assert f"vrcpilot_tap_{real_pid}" not in sinks_final
            assert f"vrcpilot_tap_{ghost_pid}" not in sinks_final

    def test_stale_tap_for_dead_pid_is_swept_on_start(self) -> None:
        """A leftover ``vrcpilot_tap_<dead_pid>`` from a prior crashed run must
        be unloaded the next time any backend starts up."""
        import os

        import pulsectl  # type: ignore[import-not-found]

        # Pick a definitely-dead PID. ``2**31 - 1`` is the max int32
        # the kernel uses; even hosts with tuned ``pid_max`` rarely
        # come close, and ``psutil.pid_exists`` will return False here.
        dead_pid = 2**31 - 1
        assert not __import__("psutil").pid_exists(dead_pid)

        with pulsectl.Pulse("vrcpilot-test-prepare-stale") as p:
            stale_module_id = p.module_load(
                "module-null-sink", _null_sink_args(dead_pid)
            )
            # Sanity: the stale module is currently loaded.
            args_now = [getattr(m, "argument", "") or "" for m in p.module_list()]
            assert any(f"sink_name=vrcpilot_tap_{dead_pid}" in arg for arg in args_now)

        # Now spin up a normal backend; its constructor must sweep the
        # stale module away.
        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        try:
            with pulsectl.Pulse("vrcpilot-test-after-stale-sweep") as p:
                args_after_start = [
                    getattr(m, "argument", "") or "" for m in p.module_list()
                ]
                assert not any(
                    f"sink_name=vrcpilot_tap_{dead_pid}" in arg
                    for arg in args_after_start
                ), "stale tap for dead pid must be unloaded on start-up"
        finally:
            backend.close()
            # Belt-and-braces: if the sweep didn't run for any reason,
            # don't leave the stale module behind for other tests.
            with pulsectl.Pulse("vrcpilot-test-stale-cleanup") as p:
                for module in p.module_list():
                    if getattr(module, "name", None) != "module-null-sink":
                        continue
                    arg = getattr(module, "argument", "") or ""
                    if f"sink_name=vrcpilot_tap_{dead_pid}" not in arg:
                        continue
                    index = getattr(module, "index", None)
                    if isinstance(index, int):
                        try:
                            p.module_unload(index)
                        except Exception:  # noqa: BLE001
                            pass
                # In case the original load somehow survived the sweep,
                # also pop the recorded id so the test isn't flaky on
                # repeated runs against the same daemon.
                try:
                    p.module_unload(stale_module_id)
                except Exception:  # noqa: BLE001
                    pass
