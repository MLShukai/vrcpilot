"""Linux PipeWire virtual-mic registration.

Installs a persistent ``VRCPilotMic`` null-sink that
:class:`vrcpilot.mic.Mic` writes float32 PCM into and VRChat reads via
``Monitor of VRCPilotMic``. Registration has two planes:

* **Persistence**: a PipeWire config fragment under
  ``$XDG_CONFIG_HOME/pipewire/pipewire.conf.d/vrcpilot-mic.conf``
  (or ``~/.config/...``) is the source of truth -- it survives restarts.
* **Immediate runtime load** (opt-in via ``runtime_load=True``): a
  ``pulsectl`` ``module_load`` so the sink works in the current session
  without restarting PipeWire. Failures degrade to a warning on
  :attr:`RegisterResult.runtime_warning`; they never mask a successful
  config write.

``pulsectl`` is imported lazily inside :func:`open_pulse_control` -- the
single seam every caller (``register`` / ``unregister`` / ``status``)
funnels through, so tests patch one symbol to cover all three paths
and hosts without ``pulsectl`` can still write the persistent config.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

# Runtime guard: importing this module off-Linux is a programming
# error. Skip the raise during type-checking so pyright analyses the
# module on every platform (otherwise the CLI wrapper module sees
# Unknown symbols when checked from Windows).
if not TYPE_CHECKING and sys.platform != "linux":
    raise RuntimeError("vrcpilot.mic.linux is Linux-only")

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from vrcpilot.mic.base import VIRTUAL_MIC_SINK_NAME

_logger = logging.getLogger(__name__)

#: PipeWire config fragment that declares the ``VRCPilotMic`` null-sink.
#: Mirrors the runtime ``module_load`` arguments below so PipeWire
#: rebuilds the same sink after a restart / re-login.
_PIPEWIRE_CONF: Final[str] = """\
context.modules = [
    {   name = libpipewire-module-null-sink
        args = {
            node.name        = "VRCPilotMic"
            node.description = "VRCPilot Virtual Mic"
            media.class      = "Audio/Sink"
            audio.position   = [ FL FR ]
            audio.rate       = 48000
            monitor.channel-volumes = true
        }
    }
]
"""

#: Filename inside ``pipewire.conf.d/`` for the fragment above.
_CONF_FILENAME: Final[str] = "vrcpilot-mic.conf"

#: ``module_load`` arguments mirroring the persistent config. PipeWire
#: accepts PulseAudio-style ``module-null-sink`` args via libpulse, and
#: ``device.description`` is written with an underscore so the value
#: stays a single PulseAudio token (matches
#: ``src/vrcpilot/speaker/pipewire.py``'s style).
_NULL_SINK_ARGS: Final[str] = (
    f"sink_name={VIRTUAL_MIC_SINK_NAME} "
    "sink_properties=device.description=VRCPilot_Virtual_Mic "
    "rate=48000 channels=2 format=float32le channel_map=front-left,front-right"
)


@dataclass(frozen=True)
class RegisterResult:
    """Outcome of :func:`register_virtual_mic`.

    Attributes:
        config_path: Absolute path to the persistent config fragment.
        created_config: Whether this call wrote the file (``False`` if
            it already existed with the expected contents).
        runtime_loaded: Whether the immediate ``pulsectl`` load
            succeeded. ``False`` when skipped via
            ``runtime_load=False`` or when the load failed -- see
            :attr:`runtime_warning` to distinguish.
        runtime_warning: Human-readable description of the runtime-load
            failure, or ``None`` on success / skip.
    """

    config_path: Path
    created_config: bool
    runtime_loaded: bool
    runtime_warning: str | None


def config_path() -> Path:
    """Absolute path of the PipeWire config fragment.

    Honours ``$XDG_CONFIG_HOME`` per the XDG Base Directory Spec,
    falling back to ``~/.config`` when unset/empty. Public so
    ``vrcpilot linux-mic status`` can surface the location and so unit
    tests can read it without depending on private internals.
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".config"
    return root / "pipewire" / "pipewire.conf.d" / _CONF_FILENAME


def open_pulse_control(client_name: str = "vrcpilot-mic") -> Any:
    """Open the ``pulsectl.Pulse`` connection every mic path shares.

    The single seam ``register`` / ``unregister`` / ``status`` funnel
    through; tests patch this symbol to inject a
    :class:`tests.fakes.FakePulse`. ``pulsectl`` is imported lazily so
    hosts without it still get to write the persistent config (the
    runtime-load step degrades to a warning instead). ``client_name``
    flows into ``pactl list short clients`` so each entry point is
    distinguishable in PulseAudio diagnostics.

    Raises:
        ImportError: ``pulsectl`` is not installed.
    """
    # ``pulsectl`` is a Linux-only conditional dependency
    # (``sys_platform == 'linux'`` in pyproject.toml); silence the
    # missing-import + unknown-type fallout when pyright runs on Windows.
    from pulsectl import (  # pyright: ignore[reportMissingTypeStubs, reportMissingImports]
        Pulse,  # pyright: ignore[reportUnknownVariableType]
    )

    return Pulse(client_name)  # pyright: ignore[reportUnknownVariableType]


def is_registered() -> bool:
    """Whether the persistent PipeWire config fragment is in place."""
    return config_path().exists()


def _write_config(path: Path) -> bool:
    """Write the config fragment; ``True`` iff the file actually changed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == _PIPEWIRE_CONF:
        return False
    path.write_text(_PIPEWIRE_CONF)
    return True


def _unload_matching_null_sinks(pulse: Any) -> int:
    """Unload every ``module-null-sink`` targeting
    :data:`VIRTUAL_MIC_SINK_NAME`.

    Shared between ``register`` (stale-cleanup before a fresh load) and
    ``unregister`` (full teardown) so the matching predicate stays
    canonical. Per-entry failures are logged and treated as "this entry
    not unloaded"; this function itself never raises.
    """
    try:
        modules: list[Any] = pulse.module_list()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    except Exception as exc:  # noqa: BLE001
        _logger.warning("module_list failed: %s", exc)
        return 0

    unloaded = 0
    for module in modules:  # pyright: ignore[reportUnknownVariableType]
        module_obj: object = module
        name = getattr(module_obj, "name", None)
        arg = getattr(module_obj, "argument", None) or ""
        if (
            name != "module-null-sink"
            or f"sink_name={VIRTUAL_MIC_SINK_NAME}" not in arg
        ):
            continue
        index = getattr(module_obj, "index", None)
        if not isinstance(index, int):
            continue
        try:
            pulse.module_unload(index)  # pyright: ignore[reportUnknownMemberType]
            unloaded += 1
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Failed to unload module-null-sink %d: %s", index, exc)
    return unloaded


def _runtime_load_null_sink() -> str | None:
    """Load (or reload) the ``VRCPilotMic`` null-sink via ``pulsectl``.

    Returns ``None`` on success or a human-readable warning string on
    failure (missing ``pulsectl``, control-plane error, etc.) -- the
    caller surfaces it via :attr:`RegisterResult.runtime_warning`.
    """
    try:
        pulse = open_pulse_control("vrcpilot-mic-register")
    except ImportError as exc:
        msg = (
            "pulsectl is not installed; the persistent config was written "
            f"but the sink will not be available until PipeWire restarts ({exc})"
        )
        _logger.warning(msg)
        return msg
    except Exception as exc:  # noqa: BLE001
        msg = (
            "could not open pulsectl control connection; the persistent "
            "config was written but the sink will not be available until "
            f"PipeWire restarts ({exc})"
        )
        _logger.warning(msg)
        return msg

    try:
        # Re-runs must not stack two null-sinks; mirrors
        # ``_reset_stale_modules`` in ``src/vrcpilot/speaker/pipewire.py``.
        _unload_matching_null_sinks(pulse)

        try:
            pulse.module_load(  # pyright: ignore[reportUnknownMemberType]
                "module-null-sink", _NULL_SINK_ARGS
            )
        except Exception as exc:  # noqa: BLE001
            msg = (
                "pulsectl module_load failed; the persistent config was "
                "written but the sink will not be available until PipeWire "
                f"restarts ({exc})"
            )
            _logger.warning(msg)
            return msg
    finally:
        try:
            pulse.close()  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("pulse close failed: %s", exc)

    return None


def register_virtual_mic(*, runtime_load: bool = True) -> RegisterResult:
    """Persist the ``VRCPilotMic`` null-sink and (optionally) load it now.

    Args:
        runtime_load: When ``True`` (default), also invoke
            ``pulsectl.Pulse.module_load`` so the sink works in the
            current session. ``False`` skips the live load -- useful
            for headless CI / chroot setups without a PipeWire daemon.

    Returns:
        A :class:`RegisterResult`. Runtime failures surface via
        :attr:`RegisterResult.runtime_warning` rather than raising; the
        persistent config either writes successfully or an
        :class:`OSError` propagates from the filesystem layer.
    """
    path = config_path()
    created_config = _write_config(path)

    if not runtime_load:
        return RegisterResult(
            config_path=path,
            created_config=created_config,
            runtime_loaded=False,
            runtime_warning=None,
        )

    warning = _runtime_load_null_sink()
    return RegisterResult(
        config_path=path,
        created_config=created_config,
        runtime_loaded=warning is None,
        runtime_warning=warning,
    )


def _runtime_unload_null_sink() -> bool:
    """Unload any live ``VRCPilotMic`` null-sinks; ``True`` iff any matched.

    Missing ``pulsectl`` or control-plane errors are logged and treated
    as "nothing unloaded" -- this is unregister's runtime half, not the
    source of truth, so a failure here never blocks the config delete.
    """
    try:
        pulse = open_pulse_control("vrcpilot-mic-unregister")
    except ImportError as exc:
        _logger.warning(
            "pulsectl is not installed; cannot runtime-unload VRCPilotMic (%s)",
            exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "could not open pulsectl control connection for unload: %s", exc
        )
        return False

    try:
        count = _unload_matching_null_sinks(pulse)
    finally:
        try:
            pulse.close()  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("pulse close failed: %s", exc)
    return count > 0


def unregister_virtual_mic() -> bool:
    """Remove the persistent config and unload the runtime sink.

    Returns ``True`` iff anything was actually removed (config file,
    runtime module, or both); ``False`` when neither artefact existed.
    """
    path = config_path()
    removed_file = False
    if path.exists():
        path.unlink()
        removed_file = True

    runtime_unloaded = _runtime_unload_null_sink()
    return removed_file or runtime_unloaded
