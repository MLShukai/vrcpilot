"""Tests for :mod:`vrcpilot.mic.linux`.

Two test universes live here:

* **Hermetic config-write tests** -- ``register_virtual_mic`` /
  ``unregister_virtual_mic`` / ``config_path`` / ``is_registered`` only
  touch ``$XDG_CONFIG_HOME`` and ``pulsectl`` via the
  :func:`vrcpilot.mic.linux.open_pulse_control` seam. With
  ``runtime_load=False`` they need nothing but ``tmp_path``.
* **Integration-real runtime tests** -- when ``pulsectl`` is installed
  and a PipeWire / PulseAudio server is reachable, the runtime-load
  path is exercised against the real control plane. A unique sink
  name keeps the test isolated from any production
  ``VRCPilotMic`` already registered on the host.

Per the project testing policy, 3rd-party-library surface fakes
(``FakePulse`` etc.) are intentionally not used here. The previous
test file mocked ``pulsectl.Pulse`` -- that style is now forbidden.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

if not sys.platform.startswith("linux"):
    pytest.skip("vrcpilot.mic.linux is Linux-only", allow_module_level=True)

# Re-binding ``vrcpilot.mic.linux.open_pulse_control`` to raise
# ``ImportError`` lets the hermetic tests run on machines that lack
# ``pulsectl`` entirely. The integration-real tests below probe for
# both ``pulsectl`` and a live server and skip if either is absent.

from vrcpilot.mic import linux as mic_linux  # noqa: E402
from vrcpilot.mic.base import VIRTUAL_MIC_SINK_NAME  # noqa: E402


@pytest.fixture
def isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``$XDG_CONFIG_HOME`` at ``tmp_path`` for the duration of a test.

    Returns ``tmp_path`` so the test can assert against the resolved
    fragment path without re-deriving the XDG layout.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def no_pulsectl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``open_pulse_control`` to raise ``ImportError``.

    Used by tests in the hermetic universe that should never touch the
    real control plane even on hosts where ``pulsectl`` is installed.
    The function is the documented single seam (``register`` /
    ``unregister`` / ``status`` all funnel through it), so substituting
    it here keeps the test pure.
    """

    def boom(client_name: str = "vrcpilot-mic") -> object:
        del client_name
        raise ImportError("pulsectl unavailable for this test")

    monkeypatch.setattr(mic_linux, "open_pulse_control", boom)


# ---------------------------------------------------------------------------
# Hermetic: config_path
# ---------------------------------------------------------------------------


class TestConfigPathResolution:
    def test_uses_xdg_config_home_when_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = mic_linux.config_path()
        assert path == tmp_path / "pipewire" / "pipewire.conf.d" / "vrcpilot-mic.conf"

    def test_falls_back_to_home_config_when_xdg_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        path = mic_linux.config_path()
        assert path == (
            tmp_path / ".config" / "pipewire" / "pipewire.conf.d" / "vrcpilot-mic.conf"
        )

    def test_empty_xdg_config_home_falls_back_to_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An empty XDG_CONFIG_HOME is equivalent to "unset" in the XDG
        # spec; users who export the variable to clear it should still
        # land in ~/.config rather than at the filesystem root.
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        monkeypatch.setenv("HOME", str(tmp_path))
        path = mic_linux.config_path()
        assert path.is_relative_to(tmp_path / ".config")


# ---------------------------------------------------------------------------
# Hermetic: persistent config fragment
# ---------------------------------------------------------------------------


class TestPersistentConfigFragment:
    def test_register_writes_pipewire_1_0_plus_syntax(
        self,
        isolate_config: Path,
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # Critical regression guard: PipeWire 1.0+ removed the
        # standalone libpipewire-module-null-sink module, and a config
        # that still references it crashes the daemon on start-up
        # (vrcpilot has been bitten by this before -- see
        # memory/project_pipewire_null_sink_module_removed.md). The
        # fragment must use the context.objects / adapter +
        # support.null-audio-sink form instead.
        result = mic_linux.register_virtual_mic(runtime_load=False)
        assert result.config_path.exists()
        contents = result.config_path.read_text()
        assert "context.objects" in contents
        assert "factory = adapter" in contents
        assert "support.null-audio-sink" in contents
        # The sink name must match VIRTUAL_MIC_SINK_NAME so the runtime
        # load and the persistent config agree on the name PipeWire
        # rebuilds on restart.
        assert f'node.name        = "{VIRTUAL_MIC_SINK_NAME}"' in contents
        # The removed-and-crashy module name must NOT appear -- that is
        # the precise string PipeWire 1.0+ rejects.
        assert "libpipewire-module-null-sink" not in contents

    def test_register_with_runtime_load_false_does_not_call_pulsectl(
        self,
        isolate_config: Path,
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # The runtime_load=False contract: the persistent config is
        # written even on hosts without pulsectl. If this regressed,
        # CI / chroot environments would lose the ability to install
        # the sink config offline.
        result = mic_linux.register_virtual_mic(runtime_load=False)
        assert result.runtime_loaded is False
        # No warning because we deliberately skipped runtime load.
        assert result.runtime_warning is None
        assert result.config_path.exists()
        del isolate_config

    def test_idempotent_config_write_reports_unchanged(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # A second register must not re-write the file if its contents
        # are already correct; created_config flips to False so callers
        # can distinguish a fresh install from a no-op idempotent run
        # (the CLI's "already registered" UX depends on this signal).
        first = mic_linux.register_virtual_mic(runtime_load=False)
        assert first.created_config is True
        second = mic_linux.register_virtual_mic(runtime_load=False)
        assert second.created_config is False
        assert second.config_path == first.config_path

    def test_changed_config_rewrites(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # If the persistent file is corrupted or hand-edited, a fresh
        # register must overwrite it (otherwise the CLI's "re-register
        # to fix it" guidance would silently no-op).
        result = mic_linux.register_virtual_mic(runtime_load=False)
        result.config_path.write_text("# corrupted by hand\n")
        again = mic_linux.register_virtual_mic(runtime_load=False)
        assert again.created_config is True
        contents = again.config_path.read_text()
        assert "support.null-audio-sink" in contents


class TestRuntimeWarningSurfacing:
    def test_runtime_warning_emitted_when_pulsectl_missing(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # Documented behaviour: missing pulsectl downgrades to a
        # warning rather than raising, so the config write still
        # succeeds and the user is told what to do next.
        result = mic_linux.register_virtual_mic()
        assert result.runtime_loaded is False
        assert result.runtime_warning is not None
        assert "pulsectl" in result.runtime_warning


# ---------------------------------------------------------------------------
# Hermetic: unregister + is_registered round-trip
# ---------------------------------------------------------------------------


class TestUnregisterAndIsRegistered:
    def test_is_registered_reflects_config_presence(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        assert mic_linux.is_registered() is False
        mic_linux.register_virtual_mic(runtime_load=False)
        assert mic_linux.is_registered() is True

    def test_unregister_removes_persistent_config(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # The config file is the source of truth (it survives reboots);
        # unregister must take it down even when the runtime control
        # plane is unavailable, otherwise users could not undo the
        # registration on a host that lost pulsectl.
        mic_linux.register_virtual_mic(runtime_load=False)
        assert mic_linux.config_path().exists()
        removed = mic_linux.unregister_virtual_mic()
        assert removed is True
        assert not mic_linux.config_path().exists()
        assert mic_linux.is_registered() is False

    def test_unregister_returns_false_when_nothing_present(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # A no-op unregister is a valid outcome (idempotency); callers
        # use the boolean return to decide whether to log "removed".
        removed = mic_linux.unregister_virtual_mic()
        assert removed is False


# ---------------------------------------------------------------------------
# Integration-real: not covered by automated tests
# ---------------------------------------------------------------------------
#
# The runtime-load path (``_runtime_load_null_sink`` /
# ``_runtime_unload_null_sink``) talks to a real PipeWire / PulseAudio
# server via the production sink name (``VIRTUAL_MIC_SINK_NAME ==
# "VRCPilotMic"``). Hijacking the constant from a test would conflate
# the test sink with the user's production sink and risk leaving stale
# modules behind on test failure. The e2e scenarios under ``tests/e2e/``
# exercise the full register / use / unregister cycle on a real host
# instead -- that is the right place for that coverage.
