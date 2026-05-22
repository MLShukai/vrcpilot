"""Tests for :mod:`vrcpilot.speaker.linux`.

The backend talks to PipeWire / PulseAudio via four seams:

* :meth:`PipeWireSpeakerBackend._open_pulse` — substituted with
  :class:`tests.fakes.FakePulse` so we never need a real PulseAudio
  / PipeWire server.
* :meth:`PipeWireSpeakerBackend._spawn_pw_record` — substituted with
  :class:`tests.fakes.FakePwRecordProcess` so the data plane is
  driven synchronously by the test.
* :meth:`PipeWireSpeakerBackend._run_pw_dump` — substituted with a
  fixture-driven list of dicts mirroring real ``pw-dump`` output.
* :meth:`PipeWireSpeakerBackend._run_pw_link` — substituted with a
  recording :class:`unittest.mock.MagicMock` so tests assert which
  ``pw-link`` invocations the backend would have issued.

The autouse ``_no_real_vrchat`` fixture in :mod:`tests.conftest` pins
:func:`vrcpilot.process.find_pid` to ``None``. The ``patch_pid`` helper
below overrides it with a deterministic PID; the ``shutil.which`` and
``XDG_RUNTIME_DIR`` patches keep CLI / filesystem side-effects
hermetic.
"""

from __future__ import annotations

import sys

import pytest

# vrcpilot.speaker.linux raises ImportError on non-Linux, so skip
# before the production import below would crash pytest collection.
if sys.platform != "linux":
    pytest.skip(
        "PipeWireSpeakerBackend is Linux-only",
        allow_module_level=True,
    )

import json
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
from pytest_mock import MockerFixture

from tests.fakes import FakePulse, FakePulseModuleInfo, FakePwRecordProcess
from vrcpilot.speaker.base import CHANNELS
from vrcpilot.speaker.linux import PipeWireSpeakerBackend

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_pid(mocker: MockerFixture) -> int:
    """Override the autouse ``find_pid`` patch with a deterministic PID."""
    pid = 12345
    mocker.patch("vrcpilot.speaker.linux.process.find_pid", return_value=pid)
    return pid


@pytest.fixture
def mock_clis(mocker: MockerFixture) -> None:
    """All required CLIs found by :func:`shutil.which`."""
    mocker.patch(
        "vrcpilot.speaker.linux.shutil.which",
        return_value="/usr/bin/dummy",
    )


@pytest.fixture
def isolate_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``$XDG_RUNTIME_DIR`` at a tmp dir so the state file is
    hermetic."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_pulse(mocker: MockerFixture) -> FakePulse:
    """Replace ``_open_pulse`` with a fresh :class:`FakePulse`."""
    pulse = FakePulse("vrcpilot-tap")
    mocker.patch.object(PipeWireSpeakerBackend, "_open_pulse", return_value=pulse)
    return pulse


@pytest.fixture
def fake_record_proc(mocker: MockerFixture) -> FakePwRecordProcess:
    """Replace ``_spawn_pw_record`` with a fresh
    :class:`FakePwRecordProcess`."""
    proc = FakePwRecordProcess(list(("pw-record", "--target=vrcpilot_tap.monitor")))
    mocker.patch.object(PipeWireSpeakerBackend, "_spawn_pw_record", return_value=proc)
    return proc


@pytest.fixture
def pw_dump_vrchat(mocker: MockerFixture) -> list[dict[str, Any]]:
    """``_run_pw_dump`` returns one VRChat audio output node."""
    payload: list[dict[str, Any]] = [
        {
            "id": 42,
            "info": {
                "props": {
                    "media.class": "Stream/Output/Audio",
                    "application.process.binary": "VRChat.exe",
                    "application.name": "VRChat",
                    "node.name": "stream.VRChat.42",
                },
            },
        }
    ]
    mocker.patch.object(PipeWireSpeakerBackend, "_run_pw_dump", return_value=payload)
    return payload


@pytest.fixture
def pw_dump_empty(mocker: MockerFixture) -> None:
    """``_run_pw_dump`` returns no VRChat nodes."""
    mocker.patch.object(PipeWireSpeakerBackend, "_run_pw_dump", return_value=[])


@pytest.fixture
def mock_pw_link(mocker: MockerFixture) -> MagicMock:
    """Replace ``_run_pw_link`` with a recording :class:`MagicMock`."""
    return mocker.patch.object(PipeWireSpeakerBackend, "_run_pw_link")


@pytest.fixture
def disable_atexit(mocker: MockerFixture) -> MagicMock:
    """Replace the speaker.linux module's ``atexit`` reference with a mock.

    Rebinding the module-level name (rather than patching
    ``atexit.register``) keeps unrelated callers like
    ``coverage.PyTracer`` from leaking into the returned mock.
    """
    atexit_mock = MagicMock()
    mocker.patch("vrcpilot.speaker.linux.atexit", atexit_mock)
    return atexit_mock.register


@pytest.fixture
def started_backend(
    mock_clis: None,  # noqa: ARG001
    patch_pid: int,  # noqa: ARG001
    isolate_state_dir: Path,  # noqa: ARG001
    fake_pulse: FakePulse,
    fake_record_proc: FakePwRecordProcess,
    pw_dump_vrchat: list[dict[str, Any]],  # noqa: ARG001
    mock_pw_link: MagicMock,  # noqa: ARG001
    disable_atexit: MagicMock,  # noqa: ARG001
) -> Iterator[tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess]]:
    """Yield a fully-started backend plus its fakes; tears down on exit."""
    backend = PipeWireSpeakerBackend()
    try:
        yield backend, fake_pulse, fake_record_proc
    finally:
        backend.close()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestPipeWireSpeakerBackendConstruction:
    @pytest.mark.parametrize("bad", [0.0, -0.5, -1.0])
    def test_rejects_non_positive_read_timeout(
        self,
        mocker: MockerFixture,
        bad: float,
    ) -> None:
        # Validation must fire before any subprocess / pulse work.
        which_spy = mocker.patch(
            "vrcpilot.speaker.linux.shutil.which",
            return_value="/usr/bin/dummy",
        )
        with pytest.raises(ValueError, match="read_timeout must be > 0"):
            PipeWireSpeakerBackend(read_timeout=bad)
        which_spy.assert_not_called()

    def test_raises_when_clis_missing(self, mocker: MockerFixture) -> None:
        # All CLIs missing -> aggregated error message lists them.
        mocker.patch("vrcpilot.speaker.linux.shutil.which", return_value=None)
        with pytest.raises(RuntimeError, match="PipeWire backend requires"):
            PipeWireSpeakerBackend()

    def test_lists_all_missing_clis_in_error(self, mocker: MockerFixture) -> None:
        # Only pw-record + pw-link missing: error must mention each by
        # name so the user knows which package to install.
        def fake_which(name: str) -> str | None:
            if name in ("pw-record", "pw-link"):
                return None
            return "/usr/bin/" + name

        mocker.patch("vrcpilot.speaker.linux.shutil.which", side_effect=fake_which)
        with pytest.raises(RuntimeError) as excinfo:
            PipeWireSpeakerBackend()
        msg = str(excinfo.value)
        assert "pw-record" in msg
        assert "pw-link" in msg
        # Found CLIs are NOT listed.
        assert "pactl" not in msg.split("missing:")[1]
        assert "pw-dump" not in msg.split("missing:")[1]

    def test_raises_when_vrchat_not_running(self, mock_clis: None) -> None:
        del mock_clis
        # find_pid -> None (the autouse default) must surface as
        # RuntimeError, not crash deeper in pulse / subprocess.
        with pytest.raises(RuntimeError, match="VRChat is not running"):
            PipeWireSpeakerBackend()

    def test_loads_null_sink_on_start(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        _, pulse, _ = started_backend
        # The null-sink must be the single load call and carry our
        # deterministic sink name + format pin.
        assert len(pulse.module_load_calls) == 1
        name, args = pulse.module_load_calls[0]
        assert name == "module-null-sink"
        assert "sink_name=vrcpilot_tap" in args
        assert "rate=48000" in args
        assert "channels=2" in args
        assert "format=float32le" in args

    def test_unloads_stale_null_sink_first(
        self,
        mock_clis: None,  # noqa: ARG002
        patch_pid: int,  # noqa: ARG002
        isolate_state_dir: Path,  # noqa: ARG002
        fake_record_proc: FakePwRecordProcess,  # noqa: ARG002
        pw_dump_empty: None,  # noqa: ARG002
        mock_pw_link: MagicMock,  # noqa: ARG002
        disable_atexit: MagicMock,  # noqa: ARG002
        mocker: MockerFixture,
    ) -> None:
        # Pre-seed a leftover vrcpilot_tap module — a typical
        # crash-recovery scenario — and verify the backend unloads it
        # before loading a fresh one.
        pulse = FakePulse("vrcpilot-tap")
        pulse.modules.append(
            FakePulseModuleInfo(
                index=99,
                name="module-null-sink",
                argument="sink_name=vrcpilot_tap rate=48000 channels=2",
            )
        )
        # Also seed an unrelated null-sink to confirm we do NOT touch it.
        pulse.modules.append(
            FakePulseModuleInfo(
                index=100,
                name="module-null-sink",
                argument="sink_name=somebody_else",
            )
        )
        mocker.patch.object(PipeWireSpeakerBackend, "_open_pulse", return_value=pulse)

        backend = PipeWireSpeakerBackend()
        try:
            assert 99 in pulse.module_unload_calls
            assert 100 not in pulse.module_unload_calls
            # And a fresh load follows.
            assert pulse.module_load_calls
        finally:
            backend.close()

    def test_links_existing_vrchat_streams(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        mock_pw_link: MagicMock,
    ) -> None:
        del started_backend
        # The fixture's pw-dump returns one VRChat node, so pw-link
        # must be called once for each of FL / FR.
        calls = mock_pw_link.call_args_list
        assert len(calls) == 2
        sources = {c.args[0] for c in calls}
        targets = {c.args[1] for c in calls}
        assert sources == {
            "stream.VRChat.42:output_FL",
            "stream.VRChat.42:output_FR",
        }
        assert targets == {
            "vrcpilot_tap:playback_FL",
            "vrcpilot_tap:playback_FR",
        }

    def test_links_match_via_application_name_when_binary_missing(
        self,
        mock_clis: None,  # noqa: ARG002
        patch_pid: int,  # noqa: ARG002
        isolate_state_dir: Path,  # noqa: ARG002
        fake_pulse: FakePulse,  # noqa: ARG002
        fake_record_proc: FakePwRecordProcess,  # noqa: ARG002
        mock_pw_link: MagicMock,
        disable_atexit: MagicMock,  # noqa: ARG002
        mocker: MockerFixture,
    ) -> None:
        # Wine / Proton sometimes presents only application.name with
        # "VRChat" in it (no process.binary). The matcher must accept
        # that path so Linux runs are not regressed.
        mocker.patch.object(
            PipeWireSpeakerBackend,
            "_run_pw_dump",
            return_value=[
                {
                    "info": {
                        "props": {
                            "media.class": "Stream/Output/Audio",
                            "application.name": "VRChat (via Proton)",
                            "node.name": "stream.proton.VRChat",
                        }
                    }
                }
            ],
        )
        backend = PipeWireSpeakerBackend()
        try:
            assert mock_pw_link.call_count == 2
        finally:
            backend.close()

    def test_ignores_non_vrchat_streams(
        self,
        mock_clis: None,  # noqa: ARG002
        patch_pid: int,  # noqa: ARG002
        isolate_state_dir: Path,  # noqa: ARG002
        fake_pulse: FakePulse,  # noqa: ARG002
        fake_record_proc: FakePwRecordProcess,  # noqa: ARG002
        mock_pw_link: MagicMock,
        disable_atexit: MagicMock,  # noqa: ARG002
        mocker: MockerFixture,
    ) -> None:
        # A Firefox / Spotify stream sharing the bus must NOT be linked.
        mocker.patch.object(
            PipeWireSpeakerBackend,
            "_run_pw_dump",
            return_value=[
                {
                    "info": {
                        "props": {
                            "media.class": "Stream/Output/Audio",
                            "application.name": "Firefox",
                            "application.process.binary": "firefox",
                            "node.name": "stream.firefox.1",
                        }
                    }
                },
                {
                    "info": {
                        "props": {
                            "media.class": "Stream/Input/Audio",
                            "application.process.binary": "VRChat.exe",
                            "node.name": "stream.VRChat.mic",
                        }
                    }
                },
            ],
        )
        backend = PipeWireSpeakerBackend()
        try:
            assert mock_pw_link.call_count == 0
        finally:
            backend.close()

    def test_writes_state_file(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        isolate_state_dir: Path,
    ) -> None:
        del started_backend
        # The state file is a crash-recovery breadcrumb; it must
        # contain enough metadata for an external janitor to identify
        # the leaked null-sink and verify the owning PID is gone.
        state_file = isolate_state_dir / "vrcpilot" / "tap.json"
        assert state_file.exists()
        payload = json.loads(state_file.read_text())
        assert payload["sink_name"] == "vrcpilot_tap"
        assert isinstance(payload["pid"], int)
        assert isinstance(payload["module_id"], int)

    def test_subscribes_to_sink_input_events(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        _, pulse, _ = started_backend
        # Give the listener thread a brief moment to run event_mask_set
        # before we assert (the thread starts in __init__ but the
        # body's pulse calls happen asynchronously).
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and pulse.event_callback is None:
            time.sleep(0.01)
        assert pulse.event_masks == ("sink_input",)
        assert pulse.event_callback is not None

    def test_registers_atexit_close(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        disable_atexit: MagicMock,
    ) -> None:
        backend, _, _ = started_backend
        # The atexit hook is the safety-net path; if it isn't
        # registered, a crashing Python process leaks the null-sink.
        disable_atexit.assert_called_once_with(backend.close)

    def test_cleanup_on_partial_startup_failure(
        self,
        mock_clis: None,  # noqa: ARG002
        patch_pid: int,  # noqa: ARG002
        isolate_state_dir: Path,
        fake_pulse: FakePulse,
        pw_dump_vrchat: list[dict[str, Any]],  # noqa: ARG002
        mock_pw_link: MagicMock,  # noqa: ARG002
        disable_atexit: MagicMock,  # noqa: ARG002
        mocker: MockerFixture,
    ) -> None:
        # Force the pw-record spawn to fail AFTER the null-sink + state
        # file are committed. The ExitStack must unwind both so a
        # failed start-up never leaks a sink or breadcrumb.
        mocker.patch.object(
            PipeWireSpeakerBackend,
            "_spawn_pw_record",
            side_effect=OSError("pw-record not executable"),
        )
        with pytest.raises(OSError, match="pw-record not executable"):
            PipeWireSpeakerBackend()
        # Null-sink was loaded then unloaded as part of unwind.
        assert fake_pulse.module_unload_calls
        # State file rolled back too.
        assert not (isolate_state_dir / "vrcpilot" / "tap.json").exists()
        # Pulse connection closed.
        assert fake_pulse.closed


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def _wait_for_drained_bytes(
    backend: PipeWireSpeakerBackend, timeout: float = 1.0
) -> None:
    """Spin until the drain thread has copied bytes into the shared buffer."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with backend._stdout_condition:  # pyright: ignore[reportPrivateUsage]
            if backend._buffer:  # pyright: ignore[reportPrivateUsage]
                return
        time.sleep(0.01)


class TestPipeWireSpeakerBackendRead:
    def test_empty_buffer_returns_zero_shape(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, _, _ = started_backend
        # Force a tight timeout so we don't actually wait 2 s.
        backend._read_timeout = 0.05  # pyright: ignore[reportPrivateUsage]
        buf = backend.read()
        assert buf.shape == (0, CHANNELS)
        assert buf.dtype == np.float32

    def test_drains_buffer(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, _, proc = started_backend
        payload = np.array(
            [[0.25, -0.5], [1.0, -1.0], [0.0, 0.5]],
            dtype=np.float32,
        )
        proc.emit_pcm(payload.tobytes())
        _wait_for_drained_bytes(backend)

        buf = backend.read()
        np.testing.assert_array_equal(buf, payload)
        assert buf.shape == (3, CHANNELS)
        assert buf.dtype == np.float32

    def test_returned_array_is_writable(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, _, proc = started_backend
        proc.emit_pcm(np.ones((2, CHANNELS), dtype=np.float32).tobytes())
        _wait_for_drained_bytes(backend)
        buf = backend.read()
        # np.frombuffer returns a read-only view; the backend must copy
        # so DSP / sinks can mutate freely.
        buf[0, 0] = -9.0
        assert buf[0, 0] == -9.0

    def test_warns_and_drops_partial_frame(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        backend, _, proc = started_backend
        bad_payload = np.array(
            [0.1, 0.2, 0.3, 0.4, 0.5],  # 5 floats = 2 stereo frames + leftover
            dtype=np.float32,
        )
        proc.emit_pcm(bad_payload.tobytes())
        _wait_for_drained_bytes(backend)
        with caplog.at_level(logging.WARNING, logger="vrcpilot.speaker.linux"):
            buf = backend.read()
        assert buf.shape == (2, CHANNELS)
        np.testing.assert_array_equal(
            buf, np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
        )
        assert any("not divisible by" in r.getMessage() for r in caplog.records)

    def test_raises_when_closed(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, _, _ = started_backend
        backend.close()
        with pytest.raises(RuntimeError, match="closed"):
            backend.read()

    def test_raises_on_drain_thread_exception(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, _, _ = started_backend
        backend._read_timeout = 0.05  # pyright: ignore[reportPrivateUsage]
        # Plant a synthetic drain error under the condition (production
        # writes _stdout_exception while holding _stdout_condition; the
        # test mirrors that invariant so the threading model stays
        # consistent across producer and consumer).
        with backend._stdout_condition:  # pyright: ignore[reportPrivateUsage]
            backend._stdout_exception = RuntimeError(  # pyright: ignore[reportPrivateUsage]
                "stdout pipe broke"
            )
        with pytest.raises(RuntimeError, match="drain thread failed"):
            backend.read()
        # And the planted exception is consumed (one-shot).
        assert backend._stdout_exception is None  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


class TestPipeWireSpeakerBackendClose:
    def test_idempotent(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, pulse, proc = started_backend
        backend.close()
        backend.close()
        backend.close()
        # Even with three close calls the underlying steps run once.
        assert proc.terminate_calls == 1
        assert pulse.closed

    def test_terminates_pw_record(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, _, proc = started_backend
        backend.close()
        assert proc.terminate_calls == 1

    def test_unloads_null_sink(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, pulse, _ = started_backend
        # Our null-sink got module id 0 from FakePulse (monotonic).
        backend.close()
        assert 0 in pulse.module_unload_calls

    def test_unlinks_state_file(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        isolate_state_dir: Path,
    ) -> None:
        backend, _, _ = started_backend
        state_file = isolate_state_dir / "vrcpilot" / "tap.json"
        assert state_file.exists()
        backend.close()
        assert not state_file.exists()

    def test_closes_pulse_connection(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, pulse, _ = started_backend
        backend.close()
        assert pulse.closed

    def test_kills_if_terminate_timeout(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        mocker: MockerFixture,
    ) -> None:
        # Force wait() to time out so close() escalates to kill().
        import subprocess as _subprocess

        _, _, proc = started_backend
        # First wait raises TimeoutExpired; second wait (after kill) returns.
        wait_spy = mocker.patch.object(
            proc,
            "wait",
            side_effect=[
                _subprocess.TimeoutExpired(cmd="pw-record", timeout=3.0),
                0,
            ],
        )
        backend = started_backend[0]
        backend.close()
        assert proc.kill_calls == 1
        assert wait_spy.call_count == 2

    def test_warns_on_terminate_failure(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        mocker: MockerFixture,
    ) -> None:
        _, pulse, proc = started_backend
        # Patch terminate to fail before it can signal stdout EOF; we
        # close stdout manually so the drain thread still exits and
        # the 2s join timeout doesn't slow the test down.
        proc.close_stdout()
        mocker.patch.object(proc, "terminate", side_effect=OSError("subprocess gone"))
        with pytest.warns(UserWarning, match="pw-record terminate failed"):
            started_backend[0].close()
        # Downstream cleanup still completes.
        assert pulse.closed

    def test_warns_on_pulse_close_failure(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        mocker: MockerFixture,
    ) -> None:
        backend, pulse, _ = started_backend
        mocker.patch.object(pulse, "close", side_effect=RuntimeError("libpulse gone"))
        with pytest.warns(UserWarning, match="pulse close failed"):
            backend.close()


# ---------------------------------------------------------------------------
# Event listener
# ---------------------------------------------------------------------------


def _wait_for_callback_registered(pulse: FakePulse, timeout: float = 1.0) -> None:
    """Spin until the backend's listener thread has registered its callback."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and pulse.event_callback is None:
        time.sleep(0.01)


class TestPipeWireSpeakerBackendEvents:
    def test_new_sink_input_triggers_relink(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        mock_pw_link: MagicMock,
    ) -> None:
        _, pulse, _ = started_backend
        _wait_for_callback_registered(pulse)
        baseline = mock_pw_link.call_count
        pulse.emit_event("new", "sink_input", 7)
        # The callback re-runs the linker → 2 more pw-link calls
        # (one per channel) for the same VRChat node.
        assert mock_pw_link.call_count == baseline + 2

    def test_remove_event_ignored(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        mock_pw_link: MagicMock,
    ) -> None:
        _, pulse, _ = started_backend
        _wait_for_callback_registered(pulse)
        baseline = mock_pw_link.call_count
        pulse.emit_event("remove", "sink_input", 7)
        pulse.emit_event("change", "sink_input", 7)
        assert mock_pw_link.call_count == baseline

    def test_non_sink_input_facility_ignored(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
        mock_pw_link: MagicMock,
    ) -> None:
        _, pulse, _ = started_backend
        _wait_for_callback_registered(pulse)
        baseline = mock_pw_link.call_count
        pulse.emit_event("new", "source_output", 7)
        assert mock_pw_link.call_count == baseline

    def test_listener_exits_on_close(
        self,
        started_backend: tuple[PipeWireSpeakerBackend, FakePulse, FakePwRecordProcess],
    ) -> None:
        backend, pulse, _ = started_backend
        _wait_for_callback_registered(pulse)
        backend.close()
        # The event thread must have exited; the fake pulse is closed
        # and the join in close() must have completed within its 2 s
        # timeout (if it hadn't, the test would have hung).
        event_thread: threading.Thread | None = backend._event_thread  # pyright: ignore[reportPrivateUsage]
        assert event_thread is None
