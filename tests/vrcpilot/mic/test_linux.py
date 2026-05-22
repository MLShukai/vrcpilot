"""Tests for :mod:`vrcpilot.mic.linux`.

The module raises ``RuntimeError`` on import for non-Linux platforms,
so collect-time skip is mandatory. ``pulsectl`` is never imported
directly -- :func:`vrcpilot.mic.linux.open_pulse_control` is the single
seam, substituted with :class:`tests.fakes.FakePulse` via
``mocker.patch``. State is shared across the
``register_virtual_mic`` / ``unregister_virtual_mic`` cycle via
:class:`tests.fakes.FakePulseRegistry`.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "linux":
    pytest.skip("vrcpilot.mic.linux is Linux-only", allow_module_level=True)

from pathlib import Path  # noqa: E402

from pytest_mock import MockerFixture  # noqa: E402

from tests.fakes import FakePulse, FakePulseModuleInfo, FakePulseRegistry  # noqa: E402
from vrcpilot.mic import linux as mic_linux  # noqa: E402
from vrcpilot.mic.base import VIRTUAL_MIC_SINK_NAME  # noqa: E402


@pytest.fixture
def isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``$XDG_CONFIG_HOME`` at ``tmp_path`` and return the config dir."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_pulse(mocker: MockerFixture) -> FakePulseRegistry:
    """Hand out a fresh FakePulse on every ``open_pulse_control`` call.

    The returned :class:`FakePulseRegistry` aggregates state across
    calls so tests can assert on the full ``module_load`` /
    ``module_unload`` trace without caring how many connections the
    production code opened.
    """
    registry = FakePulseRegistry()
    mocker.patch.object(mic_linux, "open_pulse_control", side_effect=registry.open)
    return registry


class TestConfigPathResolution:
    def test_uses_xdg_config_home_when_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = mic_linux.config_path()
        assert path == tmp_path / "pipewire" / "pipewire.conf.d" / "vrcpilot-mic.conf"

    def test_falls_back_to_home_config_when_xdg_unset(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        path = mic_linux.config_path()
        assert path == (
            tmp_path / ".config" / "pipewire" / "pipewire.conf.d" / "vrcpilot-mic.conf"
        )

    def test_empty_xdg_config_home_falls_back_to_home(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        monkeypatch.setenv("HOME", str(tmp_path))
        path = mic_linux.config_path()
        assert path.parent.parent.parent == tmp_path / ".config"


class TestRegisterVirtualMic:
    def test_writes_config_file_with_null_sink_module(
        self, isolate_config: Path, fake_pulse: FakePulse
    ) -> None:
        result = mic_linux.register_virtual_mic()
        assert result.config_path.exists()
        assert result.config_path == (
            isolate_config / "pipewire" / "pipewire.conf.d" / "vrcpilot-mic.conf"
        )
        contents = result.config_path.read_text()
        assert 'node.name        = "VRCPilotMic"' in contents
        assert "libpipewire-module-null-sink" in contents
        assert result.created_config is True

    def test_runtime_load_calls_pulse_module_load(
        self, isolate_config: Path, fake_pulse: FakePulse
    ) -> None:
        del isolate_config
        result = mic_linux.register_virtual_mic()
        assert result.runtime_loaded is True
        assert result.runtime_warning is None
        assert len(fake_pulse.module_load_calls) == 1
        name, args = fake_pulse.module_load_calls[0]
        assert name == "module-null-sink"
        assert f"sink_name={VIRTUAL_MIC_SINK_NAME}" in args
        assert "rate=48000" in args
        assert "channels=2" in args

    def test_runtime_load_false_skips_module_load(
        self, isolate_config: Path, fake_pulse: FakePulse
    ) -> None:
        del isolate_config
        result = mic_linux.register_virtual_mic(runtime_load=False)
        assert result.runtime_loaded is False
        assert result.runtime_warning is None
        assert fake_pulse.module_load_calls == []

    def test_runtime_warning_when_pulsectl_missing(
        self,
        isolate_config: Path,
        mocker: MockerFixture,
    ) -> None:
        del isolate_config
        mocker.patch.object(
            mic_linux,
            "open_pulse_control",
            side_effect=ImportError("No module named 'pulsectl'"),
        )
        result = mic_linux.register_virtual_mic()
        assert result.config_path.exists()
        assert result.runtime_loaded is False
        assert result.runtime_warning is not None
        assert "pulsectl" in result.runtime_warning

    def test_runtime_warning_when_module_load_raises(
        self,
        isolate_config: Path,
        mocker: MockerFixture,
    ) -> None:
        del isolate_config
        pulse = FakePulse("vrcpilot-mic-register")

        def boom(name: str, args: str) -> int:
            del name, args
            raise RuntimeError("control plane error")

        mocker.patch.object(pulse, "module_load", side_effect=boom)
        mocker.patch.object(mic_linux, "open_pulse_control", return_value=pulse)
        result = mic_linux.register_virtual_mic()
        assert result.runtime_loaded is False
        assert result.runtime_warning is not None
        assert "control plane error" in result.runtime_warning

    def test_reregister_unloads_stale_module_before_loading(
        self,
        isolate_config: Path,
        fake_pulse: FakePulseRegistry,
    ) -> None:
        del isolate_config
        # Pre-seed a stale VRCPilotMic null-sink as if a prior run had
        # crashed without cleanup.
        stale = FakePulseModuleInfo(
            index=42,
            name="module-null-sink",
            argument=f"sink_name={VIRTUAL_MIC_SINK_NAME} stale-args",
        )
        fake_pulse.modules.append(stale)
        fake_pulse.next_module_id = 43

        result = mic_linux.register_virtual_mic()
        assert result.runtime_loaded is True
        # The stale module must be unloaded before the fresh load so the
        # control plane never has two VRCPilotMic null-sinks at once.
        assert 42 in fake_pulse.module_unload_calls
        assert fake_pulse.module_unload_calls.index(42) == 0
        assert len(fake_pulse.module_load_calls) == 1

    def test_idempotent_config_write_does_not_rewrite(
        self,
        isolate_config: Path,
        fake_pulse: FakePulseRegistry,
    ) -> None:
        del isolate_config
        first = mic_linux.register_virtual_mic(runtime_load=False)
        assert first.created_config is True
        second = mic_linux.register_virtual_mic(runtime_load=False)
        assert second.created_config is False
        assert second.config_path == first.config_path


class TestUnregisterVirtualMic:
    def test_removes_config_file_and_unloads_module(
        self,
        isolate_config: Path,
        fake_pulse: FakePulseRegistry,
    ) -> None:
        del isolate_config
        mic_linux.register_virtual_mic()
        loaded_index = fake_pulse.modules[-1].index
        removed = mic_linux.unregister_virtual_mic()
        assert removed is True
        assert not mic_linux.config_path().exists()
        assert loaded_index in fake_pulse.module_unload_calls

    def test_returns_false_when_nothing_to_remove(
        self,
        isolate_config: Path,
        fake_pulse: FakePulseRegistry,
    ) -> None:
        del isolate_config
        # Fresh state: no config file, no loaded module.
        removed = mic_linux.unregister_virtual_mic()
        assert removed is False
        assert fake_pulse.module_unload_calls == []

    def test_removes_file_even_when_pulse_unavailable(
        self,
        isolate_config: Path,
        mocker: MockerFixture,
    ) -> None:
        del isolate_config
        # Write config without runtime load so no fake pulse state exists.
        mocker.patch.object(
            mic_linux,
            "open_pulse_control",
            side_effect=ImportError("pulsectl missing"),
        )
        mic_linux.register_virtual_mic(runtime_load=False)
        removed = mic_linux.unregister_virtual_mic()
        assert removed is True
        assert not mic_linux.config_path().exists()


class TestIsRegistered:
    def test_false_before_register(
        self,
        isolate_config: Path,
    ) -> None:
        del isolate_config
        assert mic_linux.is_registered() is False

    def test_true_after_register(
        self,
        isolate_config: Path,
        fake_pulse: FakePulseRegistry,
    ) -> None:
        del isolate_config, fake_pulse
        mic_linux.register_virtual_mic(runtime_load=False)
        assert mic_linux.is_registered() is True

    def test_false_after_unregister(
        self,
        isolate_config: Path,
        fake_pulse: FakePulseRegistry,
    ) -> None:
        del isolate_config
        mic_linux.register_virtual_mic()
        mic_linux.unregister_virtual_mic()
        assert mic_linux.is_registered() is False
        # And the pulse module is gone too.
        assert all(
            f"sink_name={VIRTUAL_MIC_SINK_NAME}" not in (m.argument or "")
            for m in fake_pulse.modules
        )


class TestRoundTrip:
    def test_register_then_unregister_cycle(
        self,
        isolate_config: Path,
        fake_pulse: FakePulseRegistry,
    ) -> None:
        del isolate_config
        assert mic_linux.is_registered() is False
        result = mic_linux.register_virtual_mic()
        assert result.runtime_loaded is True
        assert mic_linux.is_registered() is True
        assert any(
            f"sink_name={VIRTUAL_MIC_SINK_NAME}" in (m.argument or "")
            for m in fake_pulse.modules
        )
        removed = mic_linux.unregister_virtual_mic()
        assert removed is True
        assert mic_linux.is_registered() is False
