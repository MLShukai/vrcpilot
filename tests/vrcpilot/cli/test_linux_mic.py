"""Tests for :mod:`vrcpilot.cli.linux_mic`.

The CLI front-end calls into :mod:`vrcpilot.mic.linux` (which raises
on import outside Linux) and probes ``pulsectl`` / ``sounddevice``
directly inside ``status``. Linux-only behaviour is module-skip-gated
the same way as ``tests/vrcpilot/mic/test_linux.py``; a single
``TestNonLinuxGuard`` class exercises the entry-point guard via a
local ``sys.platform`` patch -- this is the *CLI entry* guard test
(not a cross-platform claim about ``vrcpilot.mic.linux`` itself), so
the broad ``sys.platform`` mocking ban in
``memory/feedback_test_strategy.md`` does not apply.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakePulse, FakePulseModuleInfo, FakeSoundDevice
from vrcpilot.cli import linux_mic as cli_linux_mic, main


class TestNonLinuxGuard:
    """Entry-point OS guard. Verified on every platform.

    Patching ``sys.platform`` here is intentional: the guard's whole
    contract is "refuse to act on non-Linux"; testing it requires
    pretending to be one of those platforms. The ban on broad
    ``sys.platform`` mocking applies to architectural claims, not to
    targeted CLI-entry refusals.
    """

    def test_register_on_non_linux_returns_2(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mocker.patch.object(cli_linux_mic.sys, "platform", "win32")

        exit_code = main(["linux-mic", "register"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "linux-mic is Linux-only" in captured.err
        assert captured.out == ""

    def test_unregister_on_non_linux_returns_2(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mocker.patch.object(cli_linux_mic.sys, "platform", "darwin")

        exit_code = main(["linux-mic", "unregister"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "linux-mic is Linux-only" in captured.err

    def test_status_on_non_linux_returns_2(
        self,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mocker.patch.object(cli_linux_mic.sys, "platform", "win32")

        exit_code = main(["linux-mic", "status"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "linux-mic is Linux-only" in captured.err


# ---------------------------------------------------------------------------
# Linux-only fixtures + tests below.
# ---------------------------------------------------------------------------

if sys.platform != "linux":
    pytest.skip(
        "linux-mic register/unregister/status behaviour is Linux-only",
        allow_module_level=True,
    )


from vrcpilot.mic import linux as mic_linux  # noqa: E402


@pytest.fixture
def isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``$XDG_CONFIG_HOME`` at ``tmp_path``."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


class _PulseRegistry:
    """Hand out a fresh FakePulse on each ``_open_pulse`` call.

    Mirrors the registry pattern used by ``tests/vrcpilot/mic/test_linux.py``:
    each FakePulse hands out is wired to share module / id state with
    the registry so unload-after-load chains behave like a real
    PulseAudio server that survives across short-lived connections.
    """

    def __init__(self) -> None:
        self.instances: list[FakePulse] = []
        self.modules: list[FakePulseModuleInfo] = []
        self.next_module_id: int = 0

    @property
    def module_load_calls(self) -> list[tuple[str, str]]:
        return [call for inst in self.instances for call in inst.module_load_calls]

    @property
    def module_unload_calls(self) -> list[int]:
        return [idx for inst in self.instances for idx in inst.module_unload_calls]

    def open(self) -> FakePulse:
        pulse = FakePulse("vrcpilot-mic-register")
        pulse.modules = list(self.modules)
        pulse.next_module_id = self.next_module_id
        original_load = pulse.module_load
        original_unload = pulse.module_unload
        original_close = pulse.close

        def load(name: str, args: str) -> int:
            idx = original_load(name, args)
            self.modules = list(pulse.modules)
            self.next_module_id = pulse.next_module_id
            return idx

        def unload(index: int) -> None:
            original_unload(index)
            self.modules = list(pulse.modules)

        def close() -> None:
            self.modules = list(pulse.modules)
            self.next_module_id = pulse.next_module_id
            original_close()

        pulse.module_load = load  # pyright: ignore[reportAttributeAccessIssue]
        pulse.module_unload = unload  # pyright: ignore[reportAttributeAccessIssue]
        pulse.close = close  # pyright: ignore[reportAttributeAccessIssue]
        self.instances.append(pulse)
        return pulse


@pytest.fixture
def fake_pulse(mocker: MockerFixture) -> _PulseRegistry:
    """Substitute ``_open_pulse`` with a registry-backed FakePulse factory."""
    registry = _PulseRegistry()
    mocker.patch.object(mic_linux, "_open_pulse", side_effect=registry.open)
    return registry


class TestRegisterAction:
    def test_register_writes_config_and_loads_runtime(
        self,
        isolate_config: Path,
        fake_pulse: _PulseRegistry,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = main(["linux-mic", "register"])

        assert exit_code == 0
        cfg = isolate_config / "pipewire" / "pipewire.conf.d" / "vrcpilot-mic.conf"
        assert cfg.exists()
        # Runtime load must have happened (one module_load call).
        assert len(fake_pulse.module_load_calls) == 1
        captured = capsys.readouterr()
        assert "Wrote PipeWire config" in captured.err
        assert str(cfg) in captured.err
        assert "Loaded module-null-sink immediately" in captured.err
        assert "Monitor of VRCPilot Virtual Mic" in captured.err
        assert captured.out == ""

    def test_register_no_runtime_load_skips_runtime(
        self,
        isolate_config: Path,
        fake_pulse: _PulseRegistry,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = main(["linux-mic", "register", "--no-runtime-load"])

        assert exit_code == 0
        assert fake_pulse.module_load_calls == []
        cfg = isolate_config / "pipewire" / "pipewire.conf.d" / "vrcpilot-mic.conf"
        assert cfg.exists()
        captured = capsys.readouterr()
        assert "Wrote PipeWire config" in captured.err
        # Not loaded -> no immediate-load banner, and no warning either
        # (runtime was deliberately skipped, not failed).
        assert "Loaded module-null-sink immediately" not in captured.err
        assert "Restart PipeWire" not in captured.err
        # User-guidance line still printed (config is the source of truth).
        assert "Monitor of VRCPilot Virtual Mic" in captured.err

    def test_register_runtime_failure_still_exits_zero(
        self,
        isolate_config: Path,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del isolate_config
        mocker.patch.object(
            mic_linux,
            "_open_pulse",
            side_effect=ImportError("No module named 'pulsectl'"),
        )

        exit_code = main(["linux-mic", "register"])

        # Persistent config is the source of truth; runtime warning
        # does not poison the exit code.
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Wrote PipeWire config" in captured.err
        assert "warning:" in captured.err
        assert "Restart PipeWire" in captured.err
        assert "systemctl --user restart pipewire" in captured.err


class TestUnregisterAction:
    def test_unregister_after_register_reports_removal(
        self,
        isolate_config: Path,
        fake_pulse: _PulseRegistry,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        register_code = main(["linux-mic", "register"])
        assert register_code == 0
        capsys.readouterr()  # discard register-action output

        unregister_code = main(["linux-mic", "unregister"])

        assert unregister_code == 0
        cfg = isolate_config / "pipewire" / "pipewire.conf.d" / "vrcpilot-mic.conf"
        assert not cfg.exists()
        # At least one module_unload happened (the loaded null-sink).
        assert len(fake_pulse.module_unload_calls) >= 1
        captured = capsys.readouterr()
        assert "Removed VRCPilotMic config and/or runtime sink" in captured.err

    def test_unregister_when_nothing_present(
        self,
        isolate_config: Path,
        fake_pulse: _PulseRegistry,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del isolate_config, fake_pulse

        exit_code = main(["linux-mic", "unregister"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No VRCPilotMic registration to remove" in captured.err


class TestStatusAction:
    def test_status_all_present(
        self,
        isolate_config: Path,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # config: present -- write the file out of band.
        cfg = isolate_config / "pipewire" / "pipewire.conf.d" / "vrcpilot-mic.conf"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("placeholder")

        # runtime: loaded -- pulsectl.Pulse returns a fake with our sink.
        pulse = FakePulse("vrcpilot-mic-status")
        pulse.modules.append(
            FakePulseModuleInfo(
                index=7,
                name="module-null-sink",
                argument="sink_name=VRCPilotMic rate=48000",
            )
        )
        mocker.patch(
            "pulsectl.Pulse",
            return_value=pulse,
        )

        # sounddevice: visible -- the fake exposes our device by name.
        fake_sd = FakeSoundDevice()
        fake_sd.add_output_device("VRCPilotMic")
        mocker.patch.dict(sys.modules, {"sounddevice": fake_sd})

        exit_code = main(["linux-mic", "status"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "config: present" in captured.out
        assert f"config_path: {cfg}" in captured.out
        assert "runtime: loaded" in captured.out
        assert "sounddevice: visible" in captured.out

    def test_status_all_absent(
        self,
        isolate_config: Path,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del isolate_config
        # runtime: not loaded -- the fake has no matching module.
        pulse = FakePulse("vrcpilot-mic-status")
        mocker.patch(
            "pulsectl.Pulse",
            return_value=pulse,
        )

        # sounddevice: not visible -- no matching device registered.
        fake_sd = FakeSoundDevice()
        fake_sd.add_output_device("Some Other Output")
        mocker.patch.dict(sys.modules, {"sounddevice": fake_sd})

        exit_code = main(["linux-mic", "status"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "config: absent" in captured.out
        assert "runtime: not loaded" in captured.out
        assert "sounddevice: not visible" in captured.out

    def test_status_sounddevice_missing_reports_error(
        self,
        isolate_config: Path,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del isolate_config
        pulse = FakePulse("vrcpilot-mic-status")
        mocker.patch("pulsectl.Pulse", return_value=pulse)

        # Force the sounddevice import inside status to fail.
        original_import = (
            __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__
        )

        def fake_import(
            name: str,
            globals: dict[str, object] | None = None,  # noqa: A002
            locals: dict[str, object] | None = None,  # noqa: A002
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name == "sounddevice":
                raise ImportError("no sounddevice in this fake env")
            return original_import(name, globals, locals, fromlist, level)

        mocker.patch("builtins.__import__", side_effect=fake_import)

        exit_code = main(["linux-mic", "status"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "sounddevice: not visible" in captured.out
        assert "error:" in captured.out

    def test_status_pulsectl_missing_reports_error(
        self,
        isolate_config: Path,
        mocker: MockerFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del isolate_config
        # sounddevice must still resolve -- patch it before forcing the
        # pulsectl import error so only one branch goes red.
        fake_sd = FakeSoundDevice()
        mocker.patch.dict(sys.modules, {"sounddevice": fake_sd})

        original_import = (
            __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__
        )

        def fake_import(
            name: str,
            globals: dict[str, object] | None = None,  # noqa: A002
            locals: dict[str, object] | None = None,  # noqa: A002
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name == "pulsectl":
                raise ImportError("no pulsectl in this fake env")
            return original_import(name, globals, locals, fromlist, level)

        mocker.patch("builtins.__import__", side_effect=fake_import)

        exit_code = main(["linux-mic", "status"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "runtime: not loaded" in captured.out
        assert "error:" in captured.out
