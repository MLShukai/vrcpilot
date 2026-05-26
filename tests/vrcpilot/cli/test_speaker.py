"""Tests for :mod:`vrcpilot.cli.speaker`.

``vrcpilot speaker`` has two actions:

* ``list`` -- emits a YAML payload with the ``devices`` key (default
  speaker first, then name-ascending) and exits 0 on success.
* ``route`` -- opens a PID-scoped audio relay until ``Ctrl+C``. Prints a
  one-line stderr summary (``route: pid=<N> device=<NAME!r>``, with
  ``(system default)`` appended when ``--device`` is omitted) and maps
  exceptions raised by the routing layer to ``vrcpilot: <msg>`` +
  exit 1.

These tests drive the CLI in-process through
:func:`vrcpilot.cli.build_parser` and :func:`vrcpilot.cli.main`, and
substitute vrcpilot's own concrete ``list_devices`` / ``route``
attachment points inside :mod:`vrcpilot.cli.speaker` with local
stand-ins. The stand-ins replace **vrcpilot-owned** symbols, not 3rd-
party surfaces -- ``soundcard`` / ``time.sleep`` / ``subprocess`` / etc.
are never patched per the project's testing policy
(``.claude/skills/vrcpilot-testing/SKILL.md``).

Open Question Q2 (spec §12) -- FakeRouter is defined **locally** in this
file rather than in ``tests/fakes/audio.py``. This keeps the spec-test
file self-contained and avoids a concurrent edit collision with the
agent owning ``tests/fakes/audio.py``.

Open Question Q3 (spec §12) -- We avoid patching ``time.sleep``
(a stdlib surface forbidden by the skill) and instead end the relay's
``while True: time.sleep(0.5)`` loop by triggering a real
``KeyboardInterrupt`` via :func:`_thread.interrupt_main`. The fake
schedules a SIGINT on the main interpreter right before the CLI enters
its sleep loop; the real ``time.sleep`` then exits with a genuine
``KeyboardInterrupt`` (the very signal the CLI's outer
``except KeyboardInterrupt`` was written for). Two variants are used:

* For tests that don't need the stderr summary (argparse plumbing),
  ``FakeRouter.__enter__`` raises ``KeyboardInterrupt`` directly so the
  CLI exits before any sleep. The ``route()`` arguments were already
  captured by the fake before the Router context was entered.
* For the summary tests, ``FakeRouter.__enter__`` returns ``self``,
  letting the CLI print the summary line; ``_thread.interrupt_main()``
  is scheduled to fire on the next ``time.sleep`` so the loop unwinds
  through real signal-delivery semantics.
"""

from __future__ import annotations

import _thread
import argparse
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

import pytest
import yaml

from vrcpilot.cli import build_parser, main

# ---------------------------------------------------------------------
# Local stand-ins (Q2 decision: local, not shared)
# ---------------------------------------------------------------------


@dataclass
class FakeAudioDevice:
    """Stand-in for :class:`vrcpilot.speaker.routing.AudioDevice`.

    The CLI only reads ``.id`` / ``.name`` / ``.is_default`` for ``list``
    and ``.name`` for ``route``'s stderr summary, so a plain dataclass
    is sufficient. We don't mirror ``frozen=True`` / ``slots=True``:
    those properties are covered by ``test_base.py`` (the routing-side
    test file), not by the CLI contract.
    """

    id: str
    name: str
    is_default: bool


@dataclass
class FakeRouter:
    """Stand-in for :class:`vrcpilot.speaker.routing.Router`.

    Used as the value returned by the fake ``route`` helper. The CLI
    only touches ``router.device.name`` after entering the context, so
    a minimal context-manager surface is enough.

    Two ``__enter__`` knobs cover the CLI's exit paths without patching
    ``time.sleep``:

    * ``raise_on_enter``: ``__enter__`` raises the given exception
      before returning. Models a SIGINT delivered during ``Router.start``
      (the spec's clean-exit branch) and routing-layer exceptions raised
      from ``start()``.
    * ``interrupt_main_on_enter``: ``__enter__`` schedules a real
      ``SIGINT`` on the main interpreter via :func:`_thread.interrupt_main`
      and returns ``self``. The CLI runs to the stderr summary print
      and then takes a genuine ``KeyboardInterrupt`` on the next
      ``time.sleep(0.5)`` -- no stdlib mocking involved.
    """

    device: FakeAudioDevice
    raise_on_enter: BaseException | None = None
    interrupt_main_on_enter: bool = False

    def __enter__(self) -> Self:
        if self.raise_on_enter is not None:
            raise self.raise_on_enter
        if self.interrupt_main_on_enter:
            # Real SIGINT delivery -- the CLI's ``time.sleep`` loop
            # exits with a genuine ``KeyboardInterrupt`` (no patching of
            # ``time.sleep`` involved). The interrupt is scheduled from
            # a short-lived daemon ``threading.Timer`` rather than fired
            # inline, so the CLI's ``print(summary)`` (between
            # ``__enter__`` returning and the sleep loop) completes
            # before SIGINT is delivered. The 50 ms delay is short
            # enough that the test cost is negligible and long enough
            # that the print always wins the race.
            threading.Timer(0.05, _thread.interrupt_main).start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        return None


@dataclass
class RouteCallRecord:
    """Captures arguments handed to the fake ``route`` helper."""

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = field(
        default_factory=list
    )


def _install_fake_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    device: FakeAudioDevice | None = None,
    raise_on_enter: BaseException | None = None,
    interrupt_main_on_enter: bool = True,
    raise_at_call: BaseException | None = None,
) -> RouteCallRecord:
    """Patch ``vrcpilot.cli.speaker.route`` with a fake.

    Returns a record of ``(args, kwargs)`` for each invocation so tests
    can assert argparse plumbing. The fake returns a :class:`FakeRouter`
    whose ``__enter__`` either:

    * raises ``raise_on_enter`` immediately, or
    * schedules a real SIGINT via ``_thread.interrupt_main`` (default,
      ``interrupt_main_on_enter=True``) so the CLI's ``time.sleep`` loop
      exits cleanly without any stdlib patching.

    ``raise_at_call`` raises from inside the fake ``route`` function
    itself (models a failure before any Router instance is returned,
    e.g. ``find_device`` throwing).
    """
    record = RouteCallRecord()
    if device is None:
        device = FakeAudioDevice(id="dev-0", name="Default Speakers", is_default=True)

    def fake_route(*args: object, **kwargs: object) -> FakeRouter:
        record.calls.append((args, dict(kwargs)))
        if raise_at_call is not None:
            raise raise_at_call
        return FakeRouter(
            device=device,
            raise_on_enter=raise_on_enter,
            interrupt_main_on_enter=interrupt_main_on_enter,
        )

    monkeypatch.setattr("vrcpilot.cli.speaker.route", fake_route)
    return record


def _install_fake_list_devices(
    monkeypatch: pytest.MonkeyPatch,
    devices: Iterable[FakeAudioDevice] | BaseException,
) -> None:
    """Patch ``vrcpilot.cli.speaker.list_devices`` with a fake.

    If ``devices`` is an exception instance, the patched function raises
    it; otherwise it returns the iterable materialised as a list.
    """
    if isinstance(devices, BaseException):
        exc = devices

        def fake_list_devices() -> list[FakeAudioDevice]:
            raise exc

    else:
        materialised = list(devices)

        def fake_list_devices() -> list[FakeAudioDevice]:
            return materialised

    monkeypatch.setattr(
        "vrcpilot.cli.speaker.list_devices",
        fake_list_devices,
    )


# ---------------------------------------------------------------------
# T-C1, T-C2, T-C3: speaker list happy path
# ---------------------------------------------------------------------


class TestSpeakerDeviceList:
    """``vrcpilot speaker list`` YAML emission and ordering."""

    def test_exit_code_zero_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C1 -- list returns 0 with at least one device.
        _install_fake_list_devices(
            monkeypatch,
            [FakeAudioDevice(id="d1", name="A", is_default=True)],
        )
        assert main(["speaker", "list"]) == 0
        capsys.readouterr()  # drain so other tests start clean

    def test_yaml_schema_devices_key_and_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C2 -- stdout YAML must have ``devices`` key whose entries
        # carry ``{id, name, is_default}``. Schema is verified by
        # round-tripping through ``yaml.safe_load``.
        _install_fake_list_devices(
            monkeypatch,
            [
                FakeAudioDevice(id="d1", name="Alpha", is_default=True),
                FakeAudioDevice(id="d2", name="Bravo", is_default=False),
            ],
        )
        assert main(["speaker", "list"]) == 0
        out = capsys.readouterr().out
        payload = yaml.safe_load(out)
        assert isinstance(payload, dict)
        assert "devices" in payload
        assert isinstance(payload["devices"], list)
        for entry in payload["devices"]:
            assert set(entry.keys()) == {"id", "name", "is_default"}
            assert isinstance(entry["id"], str)
            assert isinstance(entry["name"], str)
            assert isinstance(entry["is_default"], bool)

    def test_yaml_preserves_input_order_from_list_devices(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C3 -- the CLI surfaces ordering from ``list_devices()``
        # verbatim (default first, then name-ascending is the routing
        # layer's responsibility, validated by ``test_devices.py``). The
        # CLI contract is "do not reshuffle".
        ordered = [
            FakeAudioDevice(id="d-default", name="Aaa", is_default=True),
            FakeAudioDevice(id="d-x", name="Mmm", is_default=False),
            FakeAudioDevice(id="d-y", name="Zzz", is_default=False),
        ]
        _install_fake_list_devices(monkeypatch, ordered)
        assert main(["speaker", "list"]) == 0
        payload = yaml.safe_load(capsys.readouterr().out)
        emitted_ids = [d["id"] for d in payload["devices"]]
        assert emitted_ids == [d.id for d in ordered]

    def test_empty_device_list_emits_empty_yaml_sequence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C4 -- spec §4.2 requires ``devices: []`` when zero devices.
        _install_fake_list_devices(monkeypatch, [])
        assert main(["speaker", "list"]) == 0
        payload = yaml.safe_load(capsys.readouterr().out)
        assert payload == {"devices": []}


# ---------------------------------------------------------------------
# T-C5, T-C6, T-C7: speaker route argparse plumbing
# ---------------------------------------------------------------------


class TestSpeakerDeviceRouteArgparse:
    """``route`` forwards argparse-parsed flags to ``route()`` unchanged."""

    def test_explicit_pid_and_device_with_default_chunk_blocksize(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C5 -- explicit --pid + --device should call route(pid=12345,
        # device='Q', chunk_seconds=0.02, blocksize=None). The CLI calls
        # ``route(pid, device, ...)`` positionally; we accept either
        # positional or keyword forms.
        record = _install_fake_route(monkeypatch)

        assert (
            main(
                [
                    "speaker",
                    "route",
                    "--pid",
                    "12345",
                    "--device",
                    "Q",
                ]
            )
            == 0
        )
        capsys.readouterr()
        assert len(record.calls) == 1
        args, kwargs = record.calls[0]
        passed_pid = args[0] if args else kwargs["pid"]
        passed_device = args[1] if len(args) >= 2 else kwargs.get("device")
        assert passed_pid == 12345
        assert passed_device == "Q"
        assert kwargs.get("chunk_seconds") == 0.02
        assert kwargs.get("blocksize") is None

    def test_device_omitted_passes_none_to_route(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C6 -- omitted --device must reach route() as ``None`` so the
        # routing layer falls back to ``default_device()``.
        record = _install_fake_route(monkeypatch)
        assert main(["speaker", "route", "--pid", "42"]) == 0
        capsys.readouterr()
        args, kwargs = record.calls[0]
        passed_device = args[1] if len(args) >= 2 else kwargs.get("device", "MISSING")
        assert passed_device is None

    def test_chunk_seconds_and_blocksize_overrides_propagate(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C7 -- non-default --chunk-seconds and --blocksize values
        # must reach route() exactly as provided.
        record = _install_fake_route(monkeypatch)
        assert (
            main(
                [
                    "speaker",
                    "route",
                    "--pid",
                    "7",
                    "--chunk-seconds",
                    "0.05",
                    "--blocksize",
                    "256",
                ]
            )
            == 0
        )
        capsys.readouterr()
        _, kwargs = record.calls[0]
        assert kwargs.get("chunk_seconds") == 0.05
        assert kwargs.get("blocksize") == 256


class TestSpeakerDeviceRouteArgparseErrors:
    """Argparse-level errors must surface as ``SystemExit(2)``."""

    def test_missing_required_pid_exits_2(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C8 -- ``--pid`` is ``required=True``; omitting it must raise
        # SystemExit(2) via argparse before route() runs.
        with pytest.raises(SystemExit) as excinfo:
            main(["speaker", "route"])
        assert excinfo.value.code == 2
        assert capsys.readouterr().err != ""


# ---------------------------------------------------------------------
# T-C9: stderr summary format
# ---------------------------------------------------------------------


class TestSpeakerDeviceRouteSummary:
    """The single-line stderr summary printed once route is up."""

    def test_summary_with_explicit_device_has_no_system_default_suffix(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C9a -- explicit --device must NOT carry "(system default)".
        device = FakeAudioDevice(id="d-x", name="CABLE Input", is_default=False)
        _install_fake_route(monkeypatch, device=device)
        assert (
            main(
                [
                    "speaker",
                    "route",
                    "--pid",
                    "100",
                    "--device",
                    "CABLE",
                ]
            )
            == 0
        )
        err = capsys.readouterr().err
        # The summary is one of the stderr lines (no other stderr
        # output is expected on a successful clean exit).
        summary_lines = [line for line in err.splitlines() if "route:" in line]
        assert len(summary_lines) == 1
        line = summary_lines[0]
        assert "pid=100" in line
        # ``repr('CABLE Input')`` formats with single quotes; the spec
        # is explicit about ``<NAME!r>``.
        assert repr("CABLE Input") in line
        assert "(system default)" not in line

    def test_summary_without_device_has_system_default_suffix(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C9b -- omitting --device appends "(system default)".
        device = FakeAudioDevice(
            id="d-default", name="Speakers (Realtek)", is_default=True
        )
        _install_fake_route(monkeypatch, device=device)
        assert main(["speaker", "route", "--pid", "200"]) == 0
        err = capsys.readouterr().err
        summary_lines = [line for line in err.splitlines() if "route:" in line]
        assert len(summary_lines) == 1
        line = summary_lines[0]
        assert "pid=200" in line
        assert repr("Speakers (Realtek)") in line
        assert "(system default)" in line


# ---------------------------------------------------------------------
# T-C10: Ctrl+C exits 0 cleanly
# ---------------------------------------------------------------------


class TestSpeakerDeviceRouteKeyboardInterrupt:
    """Ctrl+C is the spec's documented clean-exit path."""

    def test_keyboard_interrupt_during_router_start_exits_0(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C10a -- KeyboardInterrupt raised during ``Router.__enter__``
        # (i.e. during ``Router.start()``) hits the CLI's *outer*
        # ``except KeyboardInterrupt`` and must exit 0 with no
        # ``vrcpilot:`` error line. The fake raises directly from
        # ``__enter__`` to model SIGINT arriving before the relay is
        # established.
        _install_fake_route(
            monkeypatch,
            raise_on_enter=KeyboardInterrupt(),
            interrupt_main_on_enter=False,
        )
        assert main(["speaker", "route", "--pid", "12345"]) == 0
        err = capsys.readouterr().err
        assert "vrcpilot:" not in err

    def test_keyboard_interrupt_during_relay_loop_exits_0(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C10b -- KeyboardInterrupt during the relay's
        # ``while True: time.sleep(0.5)`` loop hits the CLI's *inner*
        # ``except KeyboardInterrupt`` and still exits 0. The fake
        # schedules a real SIGINT via ``_thread.interrupt_main`` from
        # ``__enter__``; the genuine ``time.sleep`` then exits with a
        # genuine ``KeyboardInterrupt`` (no stdlib patching involved).
        _install_fake_route(monkeypatch)  # default: interrupt_main_on_enter=True
        assert main(["speaker", "route", "--pid", "12345"]) == 0
        err = capsys.readouterr().err
        assert "vrcpilot:" not in err


# ---------------------------------------------------------------------
# T-C11, T-C12, T-C13: runtime failures map to exit 1 + stderr line
# ---------------------------------------------------------------------


class TestSpeakerDeviceRouteRuntimeErrors:
    """Routing-layer exceptions surface as ``vrcpilot: <msg>`` + exit 1."""

    def test_runtime_error_maps_to_exit_one_with_diagnostic(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C11 -- a generic ``RuntimeError`` (e.g. VRChat death surfaced
        # by SpeakerLoop) maps to exit 1 with a single ``vrcpilot: ...``
        # stderr line.
        _install_fake_route(
            monkeypatch,
            raise_at_call=RuntimeError("vrchat dead"),
        )
        assert main(["speaker", "route", "--pid", "12345"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err
        assert "vrchat dead" in captured.err

    def test_device_not_found_error_maps_to_exit_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C12 -- ``DeviceNotFoundError`` (subclass of
        # AudioRoutingError, subclass of RuntimeError) must be caught
        # and mapped to exit 1. We import the real symbol so the
        # exception type travels through the CLI's ``except`` clause
        # exactly as production code would handle it.
        from vrcpilot.speaker.routing import DeviceNotFoundError

        _install_fake_route(
            monkeypatch,
            raise_at_call=DeviceNotFoundError("no output device matches 'xyzzy'."),
        )
        assert (
            main(
                [
                    "speaker",
                    "route",
                    "--pid",
                    "12345",
                    "--device",
                    "xyzzy",
                ]
            )
            == 1
        )
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err
        assert "xyzzy" in captured.err

    def test_audio_routing_error_maps_to_exit_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # T-C13 -- ``AudioRoutingError`` (ambiguous-query case) maps to
        # exit 1.
        from vrcpilot.speaker.routing import AudioRoutingError

        _install_fake_route(
            monkeypatch,
            raise_at_call=AudioRoutingError("multiple output devices match"),
        )
        assert (
            main(
                [
                    "speaker",
                    "route",
                    "--pid",
                    "12345",
                    "--device",
                    "Speakers",
                ]
            )
            == 1
        )
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err
        assert "multiple output devices match" in captured.err

    def test_list_runtime_failure_maps_to_exit_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # Extra coverage for the ``list`` action: spec §F5.3 says
        # OSError / ImportError on enumeration must exit 1 with a
        # ``vrcpilot: ...`` line. Symmetric with the route-side
        # error-mapping above.
        _install_fake_list_devices(
            monkeypatch,
            OSError("libpulse missing"),
        )
        assert main(["speaker", "list"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot:" in captured.err
        assert "libpulse missing" in captured.err


# ---------------------------------------------------------------------
# Argparse defaults at the parser level (no execution)
# ---------------------------------------------------------------------


class TestSpeakerDeviceParserDefaults:
    """Defaults baked into ``argparse`` are part of the CLI contract."""

    def test_route_defaults(self):
        # Defaults: --device None, --chunk-seconds 0.02, --blocksize None.
        ns: argparse.Namespace = build_parser().parse_args(
            ["speaker", "route", "--pid", "1"]
        )
        assert ns.pid == 1
        assert ns.device is None
        assert ns.chunk_seconds == 0.02
        assert ns.blocksize is None
