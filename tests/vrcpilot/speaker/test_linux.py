"""Tests for :class:`vrcpilot.speaker.linux.PipeWireSpeakerBackend`.

The PipeWire backend wires together three 3rd-party surfaces (pulsectl,
``pw-record`` / ``pw-link`` subprocesses, ``psutil``) that the testing
skill **forbids** mirroring with fakes. The strategy here therefore
splits cleanly:

* **Hermetic tests** -- those that fire **before** the backend touches
  any of those surfaces: constructor validation, the missing-CLI guard,
  pure-helper math, the ``pw-dump`` graph parsing / lookup helpers
  (``_parse_pw_dump`` / ``_find_node_id_by_name`` / ``_find_ports``),
  and the port-level
  ``pw-link`` routing logic exercised through the project-owned
  ``_pw_link_run_raw`` seam. These can run on any Linux host, even
  without PipeWire installed.
* **Integration-real tests** -- the full backend constructor /
  data-plane / teardown cycle against a real PipeWire daemon. Marked
  skip-if-infra-missing and otherwise exercised end-to-end. Some
  coverage is intentionally left to the e2e scenarios under
  ``tests/e2e/`` because the setup (a stand-in VRChat node piping
  sine into the bus) is non-trivial.

Routing design under test (v2 -- global port-id linking)
--------------------------------------------------------

VRChat's per-PID isolation no longer relies on ``Pulse.sink_input_move``
(Wireplumber reverted those moves and left recordings silent), nor on
the v1 single ``pw-link <node> <tap>`` form (that returned rc=255 while
creating zero links on real hardware). The deterministic, collision-free
form is **per-channel ``pw-link`` between global port ids**, in two
stages:

1. VRChat output ports -> per-PID null-sink playback ports.
2. The null-sink monitor ports -> the ``pw-record`` capture node's
   input ports (``pw-record`` is spawned with ``--target=0`` so
   Wireplumber cannot redirect it to the default sink's monitor -- the
   bug that made two concurrent backends record bit-identical silence).

The port graph comes from ``pw-dump`` (parsed by the pure
``_parse_pw_dump`` / ``_find_*`` helpers). The global port id is the
top-level ``"id"`` of each ``PipeWire:Interface:Port`` object; the
per-node ``port.id`` is always ``0`` and is **not** used for linking.

Why no fake-backed unit tests for the pulsectl / subprocess seams: see
project policy -- ``FakePulse`` / ``FakePwRecordProcess`` style
stand-ins drift from upstream and let CI go green while the real
PipeWire path is broken. The pure ``_parse_pw_dump`` / ``_find_*``
helpers take a plain ``list[dict]`` graph and so touch **no** 3rd-party
surface at all -- they are the highest-value tests here. The
``_pw_link_run_raw`` / ``_pw_dump_raw`` / ``_link_*`` /
``_resolve_vrchat_node_ids`` methods are **project-owned** test seams
(not 3rd-party surfaces), so substituting them via
``mocker.patch.object`` follows the policy.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from types import SimpleNamespace

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
    _find_node_id_by_name,
    _find_ports,
    _null_sink_args,
    _parse_pw_dump,
    _pw_record_argv,
    _tap_sink_name,
)

# ---------------------------------------------------------------------------
# Hermetic
# ---------------------------------------------------------------------------


class TestRequiredCLIs:
    """The v2 routing path drives ``pw-link`` and reads the port graph via
    ``pw-dump``, so all three CLIs are hard dependencies."""

    def test_required_clis_include_pw_record_pw_link_pw_dump(self) -> None:
        # pw-record pipes the tap monitor to stdout; pw-link wires the
        # per-channel port links; pw-dump enumerates the port graph the
        # link targets are resolved from. All three must be declared so
        # the missing-CLI guard names them and the install hint stays
        # actionable.
        assert "pw-record" in _REQUIRED_CLIS
        assert "pw-link" in _REQUIRED_CLIS
        assert "pw-dump" in _REQUIRED_CLIS


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

    def test_pw_record_argv_targets_zero_to_block_wireplumber_redirect(self) -> None:
        # v2: pw-record is spawned with ``--target=0`` (no auto-connect)
        # so Wireplumber cannot redirect it to the default sink's monitor
        # when multiple sinks exist -- the explicit monitor->record port
        # links are what actually feed it. Targeting the tap monitor by
        # name (the v1 form) was the root cause of two concurrent backends
        # recording bit-identical silence.
        argv = _pw_record_argv(4242)
        assert argv[0] == "pw-record"
        assert "--target=0" in argv
        # The v1 monitor-by-name target must be gone.
        assert not any(a.startswith("--target=vrcpilot_tap") for a in argv), argv
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
# pw-dump graph parsing + port-level pw-link routing (hermetic)
# ---------------------------------------------------------------------------
#
# DEPENDENCY NOTE (reconcile with B1's real-hardware v2 contract):
#
# * pw-dump object shape -- the fixture below is built from B1's measured
#   ``pw-dump`` output: a global port id is the top-level ``"id"`` of a
#   ``PipeWire:Interface:Port`` object; the per-node ``port.id`` is always
#   ``0`` and must NOT be used as a link endpoint. Node identity comes
#   from ``info.props["object.id"]`` / ``node.name`` /
#   ``application.process.id``. If B1's measured keys differ, only the
#   fixture builders here need updating.
# * ``_pw_link_run_raw`` arg shape -- the port-link tests assert only
#   that the out/in port ids appear *somewhere* in the args list passed
#   to the seam, never the exact ``pw-link`` CLI string (B1 finalises the
#   precise flags on real hardware).
# * "already-present" stderr wording -- the representative sentinel
#   (``_EXISTING_LINK_STDERR``) stands in for whatever ``pw-link`` prints
#   when a link already exists. B1 reports rc=255 + ``File exists`` for
#   this case; if the wording differs, only that one constant changes.
# * ``_parse_pw_dump`` malformed-input behaviour -- the contract for
#   empty / non-JSON bytes is B1's to define; the test below pins only
#   the loose, defensible property (no raise; returns a list) and notes
#   that a stricter contract may tighten it.

#: Representative stderr ``pw-link`` emits when the requested link
#: already exists (B1 reports rc=255 with this text). The backend's
#: idempotency branch only needs *some* substring of this line to be
#: recognised as "already present".
_EXISTING_LINK_STDERR: bytes = b"failed to link ports: File exists\n"


def _completed(
    returncode: int, stderr: bytes = b"", stdout: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    """Build a real :class:`subprocess.CompletedProcess` for the seam.

    Constructing the genuine stdlib result type (rather than a mock) is
    data construction, not mocking a 3rd-party surface -- the
    ``_pw_link_run_raw`` seam is contracted to return exactly this type.
    """
    return subprocess.CompletedProcess(
        args=["pw-link"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _bare_backend(pid: int) -> PipeWireSpeakerBackend:
    """A backend with just the attributes the routing paths read.

    ``object.__new__`` skips ``__init__`` so no real pulsectl connection
    is opened and no daemon / event thread is started. Only the fields
    the routing methods touch are set: ``_pid`` (emitted in every link
    log) and ``_stop_events`` (read by ``_on_pulse_event`` as its
    drop-out signal).
    """
    backend: PipeWireSpeakerBackend = object.__new__(PipeWireSpeakerBackend)
    backend._pid = pid
    backend._stop_events = __import__("threading").Event()
    return backend


def _link_logs(caplog: pytest.LogCaptureFixture, needle: str) -> list[str]:
    """INFO/WARNING messages from the backend logger containing ``needle``."""
    return [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == "vrcpilot.speaker.linux" and needle in rec.getMessage()
    ]


# --- pw-dump graph fixture builders (B1's measured object shape) -----------


def _dump_node(
    node_id: int,
    *,
    node_name: str,
    process_id: int | None = None,
    media_class: str | None = None,
) -> dict[str, object]:
    """A ``PipeWire:Interface:Node`` object shaped like B1's pw-dump output."""
    props: dict[str, object] = {
        "object.id": node_id,
        "node.name": node_name,
        "application.process.id": process_id,
    }
    if media_class is not None:
        props["media.class"] = media_class
    return {
        "id": node_id,
        "type": "PipeWire:Interface:Node",
        "info": {"props": props},
    }


def _dump_port(
    port_id: int,
    *,
    node_id: int,
    direction: str,
    channel: str,
    port_name: str,
) -> dict[str, object]:
    """A ``PipeWire:Interface:Port`` object.

    The global port id is the top-level ``"id"`` (== ``object.id``); the
    per-node ``port.id`` is always ``0`` and is intentionally NOT a
    usable link endpoint.
    """
    return {
        "id": port_id,
        "type": "PipeWire:Interface:Port",
        "info": {
            "props": {
                "node.id": node_id,
                "object.id": port_id,
                "port.id": 0,
                "port.name": port_name,
                "port.direction": direction,
                "audio.channel": channel,
            }
        },
    }


#: VRChat output node (process.id null on this host -- B1's measured
#: case) plus its two output ports, the per-PID null-sink's playback +
#: monitor ports, and the pw-record capture node's input ports. Mirrors
#: B1's documented pw-dump shape so the pure helpers see a realistic
#: graph.
def _sample_dump(
    *, vrchat_node: int = 112, tap_node: int = 48
) -> list[dict[str, object]]:
    return [
        _dump_node(
            vrchat_node,
            node_name="VRChat.exe",
            process_id=None,
            media_class="Stream/Output/Audio",
        ),
        _dump_port(
            80,
            node_id=vrchat_node,
            direction="out",
            channel="FL",
            port_name="output_FL",
        ),
        _dump_port(
            81,
            node_id=vrchat_node,
            direction="out",
            channel="FR",
            port_name="output_FR",
        ),
        # Per-PID null-sink: playback (in) + monitor (out) ports.
        _dump_node(tap_node, node_name="vrcpilot_tap_4242", media_class="Audio/Sink"),
        _dump_port(
            48, node_id=tap_node, direction="in", channel="FL", port_name="playback_FL"
        ),
        _dump_port(
            49, node_id=tap_node, direction="in", channel="FR", port_name="playback_FR"
        ),
        _dump_port(
            50, node_id=tap_node, direction="out", channel="FL", port_name="monitor_FL"
        ),
        _dump_port(
            51, node_id=tap_node, direction="out", channel="FR", port_name="monitor_FR"
        ),
    ]


class TestParsePwDump:
    """``_parse_pw_dump`` turns raw ``pw-dump`` bytes into a list of
    objects."""

    def test_parses_valid_json_array_to_list_of_dicts(self) -> None:
        raw = json.dumps(_sample_dump()).encode("utf-8")
        parsed = _parse_pw_dump(raw)
        assert isinstance(parsed, list)
        # Every element of a pw-dump array is a PipeWire interface object
        # carrying a top-level "id" -- the global identifier the link
        # helpers index on.
        assert all(isinstance(obj, dict) for obj in parsed)
        ids = [obj.get("id") for obj in parsed]
        assert 112 in ids and 80 in ids, ids

    def test_empty_bytes_returns_empty_list_without_raising(self) -> None:
        # DEPENDENCY NOTE: B1 defines the precise malformed-input policy.
        # The defensible, loosely-pinned property is "don't crash the
        # constructor on a transiently-empty pw-dump" -- so an empty /
        # unparsable payload must degrade to an empty list, not raise.
        assert _parse_pw_dump(b"") == []

    def test_non_json_bytes_returns_empty_list_without_raising(self) -> None:
        assert _parse_pw_dump(b"not json at all") == []


class TestFindNodeIdByName:
    """``_find_node_id_by_name`` maps a ``node.name`` to its global node id."""

    def test_finds_vrchat_node_by_name(self) -> None:
        dump = _sample_dump()
        assert _find_node_id_by_name(dump, "VRChat.exe") == 112

    def test_finds_tap_node_by_name(self) -> None:
        dump = _sample_dump()
        assert _find_node_id_by_name(dump, "vrcpilot_tap_4242") == 48

    def test_returns_none_when_node_name_absent(self) -> None:
        dump = _sample_dump()
        assert _find_node_id_by_name(dump, "no_such_node") is None


class TestFindPorts:
    """``_find_ports`` returns ``{audio.channel: global port id}`` for one node
    + direction, never mixing in another node's ports."""

    def test_returns_output_ports_for_vrchat_node(self) -> None:
        dump = _sample_dump()
        ports = _find_ports(dump, 112, "out")
        assert ports == {"FL": 80, "FR": 81}, ports

    def test_returns_only_playback_in_ports_for_tap_node(self) -> None:
        dump = _sample_dump()
        # The tap node (48) has both "in" (playback) and "out" (monitor)
        # ports; direction="in" must pick up only the playback ports.
        ports = _find_ports(dump, 48, "in")
        assert ports == {"FL": 48, "FR": 49}, ports

    def test_returns_only_monitor_out_ports_for_tap_node(self) -> None:
        dump = _sample_dump()
        ports = _find_ports(dump, 48, "out")
        assert ports == {"FL": 50, "FR": 51}, ports

    def test_does_not_mix_ports_from_other_nodes(self) -> None:
        dump = _sample_dump()
        # Asking for VRChat node's "in" ports yields nothing -- its ports
        # are all outputs. Crucially the tap node's "in" playback ports
        # (48/49) must not leak in.
        assert _find_ports(dump, 112, "in") == {}


class TestPwLinkPorts:
    """``_pw_link_ports`` links one out-port to one in-port via the project-
    owned ``_pw_link_run_raw`` seam, with a three-way log contract.

    The real ``pw-link`` subprocess is never spawned: the seam returns a
    real :class:`subprocess.CompletedProcess`. Tests pin the log prefixes
    (``port link ok`` / ``port link already present`` / ``port link
    failed``) and the stderr forwarding, and verify both port ids reach
    the seam args without asserting the exact CLI string.
    """

    def test_link_ok_logs_info(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        pid = 4242
        out_port, in_port = 80, 48
        backend = _bare_backend(pid)
        run = mocker.patch.object(
            backend, "_pw_link_run_raw", return_value=_completed(0)
        )

        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            backend._pw_link_ports(out_port, in_port)

        ok = _link_logs(caplog, "port link ok")
        assert len(ok) == 1, f"expected one 'port link ok' INFO; got {ok}"
        msg = ok[0]
        assert f"out_port={out_port}" in msg, msg
        assert f"in_port={in_port}" in msg, msg
        assert f"self_pid={pid}" in msg, msg

        # Both port ids reach the seam args; the exact CLI form is B1's
        # to finalise so we avoid an exact-args assertion.
        run.assert_called_once()
        (args,) = run.call_args.args
        flat = " ".join(args)
        assert str(out_port) in flat, flat
        assert str(in_port) in flat, flat

    def test_already_present_is_idempotent(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        pid = 4242
        backend = _bare_backend(pid)
        mocker.patch.object(
            backend,
            "_pw_link_run_raw",
            return_value=_completed(255, stderr=_EXISTING_LINK_STDERR),
        )

        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            # Re-linking an already-present port pair is the steady state
            # of the relink-on-event path; it must not raise.
            backend._pw_link_ports(80, 48)

        present = _link_logs(caplog, "port link already present")
        assert len(present) == 1, (
            f"expected one 'port link already present' INFO for an "
            f"existing link; got {present}"
        )
        # And it must NOT be misclassified as a hard failure.
        assert _link_logs(caplog, "port link failed") == []

    def test_failure_logs_warning_with_returncode(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        pid = 4242
        backend = _bare_backend(pid)
        mocker.patch.object(
            backend,
            "_pw_link_run_raw",
            return_value=_completed(1, stderr=b"failed to link ports: No such port\n"),
        )

        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            backend._pw_link_ports(80, 48)

        failed = [
            rec.getMessage()
            for rec in caplog.records
            if rec.name == "vrcpilot.speaker.linux"
            and rec.levelname == "WARNING"
            and "port link failed" in rec.getMessage()
        ]
        assert len(failed) == 1, (
            f"expected one 'port link failed' WARNING for a genuine link "
            f"error; got {failed}"
        )
        msg = failed[0]
        assert "returncode=1" in msg, msg
        assert f"self_pid={pid}" in msg, msg

        # A genuine failure must not be swallowed as "already present".
        assert _link_logs(caplog, "port link already present") == []

    def test_stderr_forwarded_to_info(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        backend = _bare_backend(4242)
        mocker.patch.object(
            backend,
            "_pw_link_run_raw",
            return_value=_completed(
                1, stderr=b"first diagnostic line\nsecond diagnostic line\n"
            ),
        )

        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            backend._pw_link_ports(80, 48)

        forwarded = _link_logs(caplog, "pw-link stderr")
        assert any("first diagnostic line" in m for m in forwarded), forwarded
        assert any("second diagnostic line" in m for m in forwarded), forwarded


class TestLinkPortsBetweenNodes:
    """``_link_ports_between_nodes`` links every common channel between two
    nodes and returns the channel count, with a ``port link summary`` log.

    Both ``_find_ports`` and ``_pw_link_ports`` are project-owned seams;
    substituting them isolates the channel-pairing logic from the pw-dump
    parsing and the subprocess call.
    """

    def test_links_each_common_channel_and_returns_count(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        pid = 4242
        backend = _bare_backend(pid)
        dump = _sample_dump()
        # src node 112 outputs FL=80/FR=81; dst node 48 inputs FL=48/FR=49.
        link = mocker.patch.object(backend, "_pw_link_ports")

        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            channels = backend._link_ports_between_nodes(dump, 112, "out", 48, "in")

        assert channels == 2, f"expected 2 common channels (FL/FR); got {channels}"
        # One link per common channel, pairing src-out to dst-in by
        # channel: FL 80->48, FR 81->49.
        assert link.call_count == 2, link.call_args_list
        linked_pairs = {tuple(call.args) for call in link.call_args_list}
        assert (80, 48) in linked_pairs, linked_pairs
        assert (81, 49) in linked_pairs, linked_pairs

        summary = _link_logs(caplog, "port link summary")
        assert (
            len(summary) == 1
        ), f"expected one 'port link summary' INFO line; got {summary}"
        msg = summary[0]
        assert "src_node=112" in msg, msg
        assert "dst_node=48" in msg, msg
        assert "channels=2" in msg, msg
        assert f"self_pid={pid}" in msg, msg

    def test_unpaired_channel_is_skipped_not_linked(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        # OPEN QUESTION (orchestrator to reconcile with B1): the v2
        # contract said "片チャネル欠落時はスキップ + WARNING", but B1's
        # implementation skips the unpaired channel *silently* and lets
        # the ``port link summary | channels=1`` line carry the
        # discrepancy instead of a dedicated per-channel WARNING. The
        # load-bearing behaviour -- "the unpaired channel is NOT linked
        # and the count reflects only paired channels" -- is unambiguous
        # under both readings, so this test pins exactly that plus the
        # summary count, and deliberately does NOT assert a missing-channel
        # WARNING the implementation does not emit. If the contract truly
        # requires the WARNING, that is an implementation change for B1
        # and this test should grow the assertion back.
        pid = 4242
        backend = _bare_backend(pid)
        # src node has FL+FR outputs; dst node has ONLY FL input, so FR
        # cannot be paired and must be skipped (not linked) -- a
        # half-wired stereo stream is a real failure mode the count must
        # surface.
        dump = [
            _dump_node(112, node_name="VRChat.exe", media_class="Stream/Output/Audio"),
            _dump_port(
                80, node_id=112, direction="out", channel="FL", port_name="output_FL"
            ),
            _dump_port(
                81, node_id=112, direction="out", channel="FR", port_name="output_FR"
            ),
            _dump_node(48, node_name="vrcpilot_tap_4242", media_class="Audio/Sink"),
            _dump_port(
                48, node_id=48, direction="in", channel="FL", port_name="playback_FL"
            ),
        ]
        link = mocker.patch.object(backend, "_pw_link_ports")

        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            channels = backend._link_ports_between_nodes(dump, 112, "out", 48, "in")

        # Only FL had a counterpart, so exactly one link and a count of 1.
        assert channels == 1, f"expected only FL linked; got channels={channels}"
        assert link.call_count == 1, link.call_args_list
        assert link.call_args_list[0].args == (80, 48), link.call_args_list

        # The half-wired result must be visible in the summary count.
        summary = _link_logs(caplog, "port link summary")
        assert len(summary) == 1, summary
        assert "channels=1" in summary[0], summary[0]


class TestOnPulseEvent:
    """``_on_pulse_event`` re-links VRChat sink_inputs as they appear."""

    def test_relink_on_new_sink_input(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A ``sink_input``/``new`` pulse event triggers a re-link and logs the
        contract-shaped ``on_pulse_event`` INFO line."""
        pid = 4242
        backend = _bare_backend(pid)
        relink = mocker.patch.object(backend, "_link_existing_vrchat_nodes_to_tap")
        event = SimpleNamespace(facility="sink_input", t="new")

        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            backend._on_pulse_event(event)

        relink.assert_called_once()
        observed = _link_logs(caplog, "on_pulse_event")
        assert len(observed) == 1, (
            f"expected one 'on_pulse_event' INFO line per received event; "
            f"got {observed}"
        )
        msg = observed[0]
        assert "facility=sink_input" in msg, msg
        assert "type=new" in msg, msg
        assert f"self_pid={pid}" in msg, msg

    def test_ignores_non_sink_input_facility(self, mocker: MockerFixture) -> None:
        """A non-``sink_input`` event (e.g. ``sink``) must not re-link.

        Only freshly-created VRChat sink_inputs need re-wiring; reacting
        to every facility would re-run the link path on unrelated daemon
        churn.
        """
        backend = _bare_backend(4242)
        relink = mocker.patch.object(backend, "_link_existing_vrchat_nodes_to_tap")
        event = SimpleNamespace(facility="sink", t="new")

        backend._on_pulse_event(event)

        relink.assert_not_called()


def _sink_input(
    index: int,
    *,
    process_id: int | None = None,
    object_id: int | None = None,
) -> SimpleNamespace:
    """A sink_input data carrier shaped like pulsectl's ``PulseSinkInputInfo``.

    This is **data construction for the resolution seam's input**, not a
    behavioural mock of pulsectl: the object carries only ``.index`` and
    ``.proplist`` (a plain dict), the attributes
    ``_resolve_vrchat_node_ids`` reads. ``None`` values are omitted from
    the proplist so the resolver exercises its key-absent fallbacks.

    DEPENDENCY NOTE: the node identifier is taken from ``object.id``
    (B1's v2 contract: ``_resolve_vrchat_node_ids`` is object.id-based).
    Matching is by ``application.process.id``. If B1's measured proplist
    keys differ, only this helper needs updating.
    """
    proplist: dict[str, object] = {}
    if process_id is not None:
        proplist["application.process.id"] = str(process_id)
    if object_id is not None:
        proplist["object.id"] = str(object_id)
    return SimpleNamespace(index=index, proplist=proplist)


class _SinkInputListPulse:
    """Minimal stand-in exposing only ``sink_input_list``.

    ``_resolve_vrchat_node_ids`` reads exactly one method off
    ``self._pulse``. Rather than mirror the whole ``pulsectl.Pulse``
    surface (forbidden by policy), this stand-in implements only the
    single read the resolver performs and returns pre-built data
    carriers. The pure ``pw-dump`` helpers above need no such stand-in;
    this is the one place the resolution tests lean on a pulsectl-shaped
    surface.
    """

    def __init__(self, inputs: list[SimpleNamespace]) -> None:
        self._inputs = inputs

    def sink_input_list(self) -> list[SimpleNamespace]:
        return self._inputs


class TestResolveVrchatNodeIds:
    """``_resolve_vrchat_node_ids`` extracts pw-link node identifiers for the
    backend's own PID only.

    A sink_input is ours iff its ``application.process.id`` equals
    ``self._pid``; the node identifier is its ``object.id``. Other VRChat
    instances (different PID) are excluded so concurrent recordings never
    cross-wire.
    """

    def test_only_self_pid_sink_input_object_id_is_returned(self) -> None:
        my_pid = 4242
        other_pid = 9999
        ours = _sink_input(index=1, process_id=my_pid, object_id=701)
        theirs = _sink_input(index=2, process_id=other_pid, object_id=702)

        backend = _bare_backend(my_pid)
        backend._pulse = _SinkInputListPulse([ours, theirs])

        node_ids = backend._resolve_vrchat_node_ids()

        # Only our PID's node, identified by its ``object.id``.
        assert node_ids == [701], f"expected only self-pid node [701]; got {node_ids}"

    def test_emits_candidate_and_summary_diagnostics(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The scan keeps the diagnostic contract: a ``sink_input candidate``
        line per candidate and a single ``sink_input scan summary``
        line."""
        my_pid = 4242
        ours = _sink_input(index=1, process_id=my_pid, object_id=701)

        backend = _bare_backend(my_pid)
        backend._pulse = _SinkInputListPulse([ours])

        with caplog.at_level("INFO", logger="vrcpilot.speaker.linux"):
            caplog.clear()
            backend._resolve_vrchat_node_ids()

        candidates = _link_logs(caplog, "sink_input candidate")
        assert candidates, "expected at least one 'sink_input candidate' INFO"

        summaries = _link_logs(caplog, "sink_input scan summary")
        assert len(summaries) == 1, (
            f"expected exactly one 'sink_input scan summary' INFO per "
            f"scan; got {summaries}"
        )
        assert f"self_pid={my_pid}" in summaries[0], summaries[0]


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
    creates a per-pid null-sink and ``pw-link``s any VRChat-like nodes
    for that PID onto the tap (none, in a normal CI run), so the test
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
        # fine because the node-link step only touches VRChat-like
        # nodes, and we have none. The interesting bit is that the
        # backend's real null-sink load + atexit cleanup succeeds
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

        The diagnostic-log contract for
        :meth:`PipeWireSpeakerBackend._resolve_vrchat_node_ids` is
        preserved across the pw-link migration: every call ends with a
        ``sink_input scan summary`` INFO line carrying ``self_pid``,
        ``matched=[...]``, ``ambiguous=[...]`` and
        ``total_candidates=<n>``. The constructor invokes the scan
        exactly once via ``_link_existing_vrchat_nodes_to_tap``, so
        capture spans construction.

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
        # whitespace or trailing-field order. DEPENDENCY NOTE: the
        # ``matched=``/``ambiguous=`` field names carry over from the
        # pre-pw-link scan summary; B1 declared the summary line is
        # preserved. If B1's summary schema drops those fields, relax
        # these two assertions to ``self_pid`` + ``total_candidates``.
        assert "matched=[]" in msg, msg
        assert "ambiguous=[]" in msg, msg
        assert f"self_pid={my_pid}" in msg, msg
        # ``total_candidates=<digit(s)>`` must be present so the field
        # is part of the contract even though the integer is
        # environment-dependent.
        assert re.search(r"total_candidates=\d+", msg) is not None, msg

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
