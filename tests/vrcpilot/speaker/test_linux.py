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

from pytest_mock import MockerFixture  # noqa: E402

from tests.helpers import has_pipewire  # noqa: E402
from vrcpilot.speaker.linux import (  # noqa: E402
    _MODULE_LOAD_RETRIES,
    _REQUIRED_CLIS,
    PipeWireSpeakerBackend,
    _extract_tap_pid,
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
            # ``module-loopback`` is no longer one of ours — the
            # backend's tap routing is null-sink only, so the helper
            # must ignore loopback modules even when their argument
            # contains a ``vrcpilot_tap_<pid>`` token (e.g. a stale
            # third-party loopback that happens to reference our
            # monitor).
            (
                "module-loopback",
                "source=vrcpilot_tap_88.monitor sink=foo",
                None,
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
    creates a per-pid null-sink and moves any VRChat-like sink_inputs
    onto the tap (none, in a normal CI run), so the test only
    validates that the constructor and close cycle survive the real
    plumbing.
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
        # the backend's real null-sink load + atexit cleanup succeeds
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

    def test_no_loopback_module_is_loaded_for_current_pid(self) -> None:
        """The backend must NOT load a ``module-loopback`` for the per-PID tap.

        Phase A of the per-PID isolation fix removed the
        ``module-loopback`` that previously bridged
        ``vrcpilot_tap_<pid>.monitor`` back into the default sink. The
        loopback was suspected of cross-contaminating two VRChat
        instances' audio (their WAVs came out bit-identical), and live
        monitoring during recording is a deliberate UX regression
        documented in ``CHANGELOG.md``. This test pins the absence: a
        regression that re-introduces the loopback module must trip
        here, both **while** the backend is alive and **after**
        ``close()``.
        """
        import os

        my_pid = os.getpid()
        target = f"source=vrcpilot_tap_{my_pid}.monitor"
        backend = PipeWireSpeakerBackend(pid=my_pid)
        try:
            import pulsectl  # type: ignore[import-not-found]

            with pulsectl.Pulse("vrcpilot-test-probe-lb") as p:
                modules = list(p.module_list())
                loopback_args = [
                    getattr(m, "argument", "") or ""
                    for m in modules
                    if getattr(m, "name", None) == "module-loopback"
                ]
                assert not any(target in arg for arg in loopback_args), (
                    f"no module-loopback for {target} should be loaded "
                    f"during backend lifetime; saw {loopback_args}"
                )
        finally:
            backend.close()

        # Belt-and-braces: still absent after close.
        with pulsectl.Pulse("vrcpilot-test-probe-lb2") as p:
            modules_after = list(p.module_list())
            args_after = [
                getattr(m, "argument", "") or ""
                for m in modules_after
                if getattr(m, "name", None) == "module-loopback"
            ]
            assert not any(target in arg for arg in args_after), (
                f"no module-loopback for {target} should remain after "
                f"backend.close; saw {args_after}"
            )

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
        # pw-record terminate / null-sink unload runs exactly once
        # even under repeated close.
        import os

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        backend.close()
        backend.close()
        backend.close()

    def test_two_backends_have_independent_per_pid_taps(self) -> None:
        """Two backends with distinct PIDs each own a private null-sink and
        neither close path tramples the other's module.

        Phase A1' additionally pins the **per-PID client name**: the
        pipewire-pulse daemon was re-using a stale ``module-null-sink``
        index when two backends both registered as the plain
        ``vrcpilot-tap`` client and one of the two ``module_load`` calls
        came back with ``Operation canceled``. With per-PID client names
        the two backends present distinct identities to the daemon, so
        the daemon log can attribute every ``LOAD_MODULE`` /
        ``UNLOAD_MODULE`` to a specific backend and the index-reuse race
        is no longer ambiguous.
        """
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

                    # Per-PID client name contract: each backend's pulse
                    # client registers under ``vrcpilot-tap-<pid>``, and
                    # the two distinct PIDs produce two distinct client
                    # names on the daemon. This is the regression detector
                    # for the "both backends share the same client name
                    # and the daemon races their module load" bug.
                    client_names = [getattr(c, "name", "") for c in p.client_list()]
                    assert f"vrcpilot-tap-{real_pid}" in client_names, (
                        f"per-PID client name for real backend missing; "
                        f"got {client_names}"
                    )
                    assert f"vrcpilot-tap-{ghost_pid}" in client_names, (
                        f"per-PID client name for ghost backend missing; "
                        f"got {client_names}"
                    )
            finally:
                backend_ghost.close()

            # backend_ghost.close() must leave backend_real's sink alive.
            with pulsectl.Pulse("vrcpilot-test-probe-2x-after") as p:
                sinks_after_ghost = [getattr(s, "name", "") for s in p.sink_list()]
                assert f"vrcpilot_tap_{real_pid}" in sinks_after_ghost
                assert f"vrcpilot_tap_{ghost_pid}" not in sinks_after_ghost

                # And the ghost client is gone from the daemon, while
                # the real backend's client remains.
                names_after_ghost = [getattr(c, "name", "") for c in p.client_list()]
                assert f"vrcpilot-tap-{real_pid}" in names_after_ghost
                assert f"vrcpilot-tap-{ghost_pid}" not in names_after_ghost
        finally:
            backend_real.close()

        # And both are gone after the outer close.
        with pulsectl.Pulse("vrcpilot-test-probe-2x-final") as p:
            sinks_final = [getattr(s, "name", "") for s in p.sink_list()]
            assert f"vrcpilot_tap_{real_pid}" not in sinks_final
            assert f"vrcpilot_tap_{ghost_pid}" not in sinks_final

            # Both backends' pulse clients are gone, too.
            names_final = [getattr(c, "name", "") for c in p.client_list()]
            assert f"vrcpilot-tap-{real_pid}" not in names_final
            assert f"vrcpilot-tap-{ghost_pid}" not in names_final

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

    def test_diagnostic_log_emits_summary_for_non_vrchat_pid(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The sink_input scan must emit a contract-shaped INFO summary on
        every construction.

        Phase A pins the diagnostic-log contract for
        :meth:`PipeWireSpeakerBackend._enumerate_vrchat_sink_inputs`:
        every call ends with a ``sink_input scan summary`` INFO line
        carrying ``self_pid``, ``matched=[...]``, ``ambiguous=[...]``
        and ``total_candidates=<n>``. The constructor invokes the scan
        exactly once via ``_move_existing_streams_to_tap``, so capture
        spans construction.

        We use the current process PID (which is not a VRChat PID), so
        the contract holds independent of whether the host happens to
        be running a VRChat instance:

        * ``matched=[]`` — no sink_input has our ``application.process.id``.
        * ``ambiguous=[]`` — a real VRChat on the host carries its own
          ``process.id`` and is classified ``skipped-no-vrchat-marker``,
          not ``ambiguous``.
        * ``self_pid=<our pid>`` — the summary echoes back the PID this
          backend instance was constructed with.

        ``total_candidates=`` is just checked for presence with a digit
        suffix rather than a fixed value, because that count depends on
        whether the developer host is running VRChat. The contract is
        about the field being emitted; the integer is observational.
        Internal-method access for the diagnostic contract follows the
        same pattern as the stale-tap-sweep test in this class.
        """
        import os
        import re

        my_pid = os.getpid()
        # Capture spans the constructor because the constructor is the
        # only safe place to observe the synchronous scan: once the
        # event listener thread is running, pulsectl forbids blocking
        # calls from other threads.
        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            backend = PipeWireSpeakerBackend(pid=my_pid)
            try:
                summaries = [
                    rec.getMessage()
                    for rec in caplog.records
                    if rec.name == "vrcpilot.speaker.linux"
                    and rec.levelname == "INFO"
                    and "sink_input scan summary" in rec.getMessage()
                ]
            finally:
                backend.close()

        assert len(summaries) == 1, (
            f"expected exactly one 'sink_input scan summary' INFO line "
            f"per construction; got {summaries}"
        )
        msg = summaries[0]
        # Substring checks pin the contract without depending on
        # whitespace or trailing-field order.
        assert "matched=[]" in msg, msg
        assert "ambiguous=[]" in msg, msg
        assert f"self_pid={my_pid}" in msg, msg
        # ``total_candidates=<digit(s)>`` must be present so the field
        # is part of the contract even though the integer is
        # environment-dependent.
        assert re.search(r"total_candidates=\d+", msg) is not None, msg

    def test_no_post_move_verify_log_when_no_matching_sink_inputs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The ``sink_input_move post-verify`` log must only fire for streams
        that were actually moved.

        Phase A (A-6) introduces a post-move re-query log that runs
        only after a successful ``sink_input_move``. When this backend
        is constructed against a non-VRChat PID (the test process's
        own PID), no sink_input matches ``self_pid``, so
        ``_move_existing_streams_to_tap`` makes zero move calls and
        therefore zero post-verify log lines should appear. A VRChat
        instance on the host (matching some other PID) is still
        classified ``skipped-no-vrchat-marker`` rather than moved
        because its ``application.process.id`` is not ours, so the
        contract holds whether or not the developer machine happens to
        be running VRChat. This is the regression detector for "the
        post-verify log accidentally fires even when zero streams were
        moved".
        """
        import os

        my_pid = os.getpid()
        # Capture spans construction; the constructor is where the
        # synchronous move attempt happens, before the event listener
        # thread is started.
        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            backend = PipeWireSpeakerBackend(pid=my_pid)
            backend.close()

        post_verify_lines = [
            rec.getMessage()
            for rec in caplog.records
            if rec.name == "vrcpilot.speaker.linux"
            and "sink_input_move post-verify" in rec.getMessage()
        ]
        assert post_verify_lines == [], (
            f"no 'sink_input_move post-verify' log should fire when no "
            f"VRChat sink_inputs match this backend's pid; saw "
            f"{post_verify_lines}"
        )

    def test_pulse_client_name_is_per_pid_unique(self) -> None:
        """The backend's pulse control connection registers under ``vrcpilot-
        tap-<pid>``, exactly once.

        Phase A1' suffixes the pulsectl client name with the VRChat
        PID. The contract this test pins:

        * Exactly one client on the daemon is named
          ``vrcpilot-tap-<self._pid>`` while the backend is alive.
        * No legacy plain ``vrcpilot-tap`` client remains (the suffix
          replaced the old name, not added alongside it).
        * After :meth:`close`, the per-PID client is gone from the
          daemon.

        Why per-PID matters: when two backends share the client name
        ``vrcpilot-tap``, the pipewire-pulse daemon races their
        ``LOAD_MODULE`` requests and returns ``Operation canceled``
        for the second backend's module-null-sink load. The retry
        logic in :class:`TestModuleLoadRetry` handles the symptom; the
        per-PID client name addresses the root cause by giving each
        backend a stable identity on the daemon.
        """
        import os

        import pulsectl  # type: ignore[import-not-found]

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        try:
            with pulsectl.Pulse("vrcpilot-test-probe-client-name") as p:
                names = [getattr(c, "name", "") for c in p.client_list()]
            per_pid_hits = [n for n in names if n == f"vrcpilot-tap-{my_pid}"]
            assert len(per_pid_hits) == 1, (
                f"expected exactly one daemon client named "
                f"'vrcpilot-tap-{my_pid}'; got {per_pid_hits} "
                f"(full client list: {names})"
            )
            # The pre-A1' literal ``vrcpilot-tap`` (no suffix) must
            # not appear: that would mean the rename regressed.
            assert "vrcpilot-tap" not in names, (
                "legacy 'vrcpilot-tap' (no suffix) client appeared on "
                "the daemon — the per-PID rename has regressed; "
                f"full client list: {names}"
            )
        finally:
            backend.close()

        # After close, no client of either name should remain.
        with pulsectl.Pulse("vrcpilot-test-probe-client-name-after") as p:
            names_after = [getattr(c, "name", "") for c in p.client_list()]
        assert f"vrcpilot-tap-{my_pid}" not in names_after, (
            f"per-PID client 'vrcpilot-tap-{my_pid}' must be gone after "
            f"backend.close; full client list: {names_after}"
        )

    def test_pw_record_stderr_drain_thread_is_joined_on_close(self) -> None:
        """``pw-record`` stderr drain thread must not outlive ``close()``.

        Phase A (A-7) adds a stderr drain thread alongside the stdout
        drain so ``pw-record`` warning lines surface to the
        ``vrcpilot.speaker.linux`` logger. Like the stdout drain it
        must be joined cleanly during teardown; a leaked stderr thread
        would survive ``backend.close()`` and keep the subprocess pipe
        open. We check the contract behaviourally: after ``close()``,
        no ``threading.Thread`` attribute on the backend may be alive.
        This avoids hard-coding the private attribute name (the field
        could be ``_drain_err_thread`` or similar) while still pinning
        the join requirement.
        """
        import os
        import threading as _threading

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        backend.close()

        live_threads = [
            (attr, value)
            for attr in vars(backend)
            for value in (getattr(backend, attr),)
            if isinstance(value, _threading.Thread) and value.is_alive()
        ]
        assert live_threads == [], (
            f"no Thread attribute on the backend should remain alive "
            f"after close(); leaked: {live_threads}"
        )


class TestModuleLoadRawWrapper:
    """``_module_load_raw`` is a thin wrapper around ``pulse.module_load``.

    The carve-out exists so retry tests can substitute the per-attempt
    outcome via ``mocker.patch.object(backend, '_module_load_raw',
    side_effect=[...])`` without mocking ``pulsectl`` itself (which the
    project's testing policy forbids for 3rd-party surfaces). This test
    asserts the wrapper has no behaviour of its own beyond delegating
    to the underlying ``pulse.module_load``.

    Real-daemon integration: we load a module via both routes, confirm
    they return integer module ids, and clean up both. ``pulsectl`` is
    used directly (not mocked) because the contract under test is "the
    wrapper is a no-op delegate".
    """

    def setup_method(self) -> None:
        if not _required_clis_present():
            pytest.skip(f"required CLIs must all be installed: {_REQUIRED_CLIS}")
        if not _pulsectl_importable():
            pytest.skip("pulsectl is required for the real PipeWire backend")
        if not has_pipewire():
            pytest.skip("no PipeWire daemon reachable")

    def test_raw_wrapper_returns_int_module_id_from_real_daemon(self) -> None:
        """``_module_load_raw`` delegates verbatim to ``pulse.module_load`` on
        a real PipeWire-Pulse daemon.

        We bypass the full ``__init__`` here because a fully-constructed
        backend has the pulse event listener thread running, and
        pulsectl refuses blocking sync calls (``module_load``) from the
        main thread under that condition (see the project memory
        ``feedback_caplog_pulsectl_event_loop``). Bypassing init lets us
        attach a **real** ``pulsectl.Pulse`` connection that has no
        event loop running, exercise the wrapper, and verify it
        returns the integer module id the daemon assigned — confirming
        the seam is a pure delegate and not introducing any per-call
        side effect of its own.
        """
        import os

        import pulsectl  # type: ignore[import-not-found]

        my_pid = os.getpid()
        # Build a minimal backend instance with just the attributes the
        # wrapper touches: ``_pulse``. ``object.__new__`` skips
        # ``__init__`` so no event listener thread is started.
        backend: PipeWireSpeakerBackend = object.__new__(PipeWireSpeakerBackend)
        backend._pulse = pulsectl.Pulse("vrcpilot-test-raw-wrapper")
        # Use a distinct sink name so the wrapper-only test never
        # collides with the backend's own ``vrcpilot_tap_<pid>`` if a
        # real backend happens to be running in another test.
        probe_sink_name = f"vrcpilot_test_raw_wrapper_{my_pid}"
        args = (
            f"sink_name={probe_sink_name} "
            f"sink_properties=device.description=VRCPilotTestRaw_{my_pid} "
            "rate=48000 channels=2 format=float32le"
        )
        idx: object = None
        try:
            idx = backend._module_load_raw("module-null-sink", args)
            # Contract: the daemon assigns an integer module id. The
            # wrapper must return that int verbatim — anything else
            # means the seam has grown behaviour of its own (which
            # would break the retry tests that rely on substituting
            # ``_module_load_raw`` as a pure delegate).
            assert isinstance(idx, int), (
                f"_module_load_raw must return an int module id; "
                f"got {type(idx).__name__} = {idx!r}"
            )
        finally:
            if isinstance(idx, int):
                try:
                    backend._pulse.module_unload(idx)
                except Exception:  # noqa: BLE001
                    pass
            try:
                backend._pulse.close()
            except Exception:  # noqa: BLE001
                pass


class TestModuleLoadRetry:
    """``_load_module`` retries on transient failures with fixed backoff.

    Phase A1' adds retry-with-backoff to absorb the
    ``Operation canceled`` race that pipewire-pulse exhibits when two
    backends unload-then-load module-null-sinks in quick succession.
    The retry surface:

    * up to ``_MODULE_LOAD_RETRIES`` total attempts
    * each failing attempt emits a WARNING log
    * a successful retry (attempt > 1) emits an INFO log
      ``module_load retry succeeded``
    * initial-attempt success emits no retry-success INFO

    These tests substitute :meth:`PipeWireSpeakerBackend._module_load_raw`
    via ``mocker.patch.object`` after the backend has been constructed.
    That test seam is **project-owned** (not a 3rd-party surface), so
    patching it follows the policy. Because the patched seam is the
    only call site touching pulsectl from the retry loop, no blocking
    pulse sync call escapes onto the main thread while the event
    listener thread is running — the retry loop itself only calls
    ``time.sleep`` and the patched seam.
    """

    def setup_method(self) -> None:
        if not _required_clis_present():
            pytest.skip(f"required CLIs must all be installed: {_REQUIRED_CLIS}")
        if not _pulsectl_importable():
            pytest.skip("pulsectl is required for the real PipeWire backend")
        if not has_pipewire():
            pytest.skip("no PipeWire daemon reachable")

    def test_retries_on_transient_failure_and_succeeds_on_third_attempt(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Two transient failures followed by a success: ``_load_module``
        returns the third attempt's module id and logs one INFO
        ``retry succeeded`` after two WARNING attempts."""
        import os

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        try:
            # 99999 is an arbitrary placeholder int — _load_module does
            # not address the daemon with the returned id; it simply
            # returns it to the caller. Using a fake int avoids
            # actually loading (and having to unload) a real module.
            mocker.patch.object(
                backend,
                "_module_load_raw",
                side_effect=[
                    Exception("simulated transient 1"),
                    Exception("simulated transient 2"),
                    99999,
                ],
            )
            with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
                caplog.clear()
                result = backend._load_module(
                    "module-null-sink", "sink_name=foo", "null-sink"
                )

            assert result == 99999, (
                "the successful attempt's module id must be returned "
                f"verbatim; got {result!r}"
            )

            warning_attempt_msgs = [
                rec.getMessage()
                for rec in caplog.records
                if rec.name == "vrcpilot.speaker.linux"
                and rec.levelname == "WARNING"
                and "module_load attempt" in rec.getMessage()
            ]
            assert len(warning_attempt_msgs) == 2, (
                f"expected exactly 2 'module_load attempt' WARNINGs for "
                f"two transient failures; got {warning_attempt_msgs}"
            )
            # Pin the attempt counter on each line so a future
            # off-by-one in the loop is caught.
            assert any(
                "attempt 1/" in m for m in warning_attempt_msgs
            ), warning_attempt_msgs
            assert any(
                "attempt 2/" in m for m in warning_attempt_msgs
            ), warning_attempt_msgs

            success_msgs = [
                rec.getMessage()
                for rec in caplog.records
                if rec.name == "vrcpilot.speaker.linux"
                and rec.levelname == "INFO"
                and "module_load retry succeeded" in rec.getMessage()
            ]
            assert len(success_msgs) == 1, (
                f"expected exactly one 'module_load retry succeeded' "
                f"INFO line on the successful third attempt; got "
                f"{success_msgs}"
            )
            # The INFO line must name the eventual attempt number so a
            # post-mortem knows how many tries it took.
            assert "attempt=3" in success_msgs[0], success_msgs[0]
        finally:
            backend.close()

    def test_propagates_final_exception_after_all_attempts_fail(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When every attempt fails, the **last** exception propagates and one
        WARNING per attempt is logged.

        The exact exception identity matters because callers (e.g. the
        ExitStack rollback in ``__init__``) inspect the chained error
        message; if ``_load_module`` raised a generic wrapper instead of
        re-raising the underlying failure, the actionable
        ``Operation canceled`` detail would be lost.
        """
        import os

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        try:
            final_exc = RuntimeError("simulated final failure")
            mocker.patch.object(
                backend,
                "_module_load_raw",
                side_effect=[
                    RuntimeError("simulated attempt 1"),
                    RuntimeError("simulated attempt 2"),
                    final_exc,
                ],
            )
            with caplog.at_level("WARNING", logger="vrcpilot.speaker.linux"):
                caplog.clear()
                with pytest.raises(RuntimeError) as excinfo:
                    backend._load_module(
                        "module-null-sink", "sink_name=foo", "null-sink"
                    )
            # Last attempt's exception is the one that propagates;
            # this pins the "preserve the actionable error" contract.
            assert excinfo.value is final_exc, (
                "the final attempt's exception must propagate verbatim; "
                f"got {excinfo.value!r}"
            )

            warning_attempt_msgs = [
                rec.getMessage()
                for rec in caplog.records
                if rec.name == "vrcpilot.speaker.linux"
                and rec.levelname == "WARNING"
                and "module_load attempt" in rec.getMessage()
            ]
            assert len(warning_attempt_msgs) == _MODULE_LOAD_RETRIES, (
                f"expected one WARNING per failed attempt "
                f"({_MODULE_LOAD_RETRIES}); got {warning_attempt_msgs}"
            )

            # And critically: no spurious 'retry succeeded' INFO on
            # the all-fail path.
            success_msgs = [
                rec.getMessage()
                for rec in caplog.records
                if rec.name == "vrcpilot.speaker.linux"
                and "module_load retry succeeded" in rec.getMessage()
            ]
            assert success_msgs == [], (
                f"no 'retry succeeded' INFO should be logged when every "
                f"attempt fails; got {success_msgs}"
            )
        finally:
            backend.close()

    def test_first_attempt_success_logs_no_retry_succeeded_info(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """First-attempt success must NOT emit ``retry succeeded``.

        The INFO line is reserved for retries that recover from a
        transient failure — emitting it on every load would flood the
        log on the common path and dilute its diagnostic value when the
        race actually fires.
        """
        import os

        my_pid = os.getpid()
        backend = PipeWireSpeakerBackend(pid=my_pid)
        try:
            mocker.patch.object(
                backend,
                "_module_load_raw",
                side_effect=[12345],
            )
            with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
                caplog.clear()
                result = backend._load_module(
                    "module-null-sink", "sink_name=foo", "null-sink"
                )

            assert result == 12345

            success_msgs = [
                rec.getMessage()
                for rec in caplog.records
                if rec.name == "vrcpilot.speaker.linux"
                and "module_load retry succeeded" in rec.getMessage()
            ]
            assert success_msgs == [], (
                f"first-attempt success must not log 'retry succeeded'; "
                f"got {success_msgs}"
            )

            # And no attempt-failure WARNINGs either.
            warning_msgs = [
                rec.getMessage()
                for rec in caplog.records
                if rec.name == "vrcpilot.speaker.linux"
                and rec.levelname == "WARNING"
                and "module_load attempt" in rec.getMessage()
            ]
            assert warning_msgs == [], (
                f"no 'module_load attempt' WARNING expected on "
                f"first-attempt success; got {warning_msgs}"
            )
        finally:
            backend.close()
