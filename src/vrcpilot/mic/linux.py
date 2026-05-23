"""Linux PipeWire virtual-mic registration.

Installs a persistent ``VRCPilotMic`` null-sink that
:class:`vrcpilot.mic.Mic` writes float32 PCM into and VRChat reads via
``Monitor of VRCPilotMic``. Two planes:

* **Persistence**: a PipeWire config fragment under
  ``$XDG_CONFIG_HOME/pipewire/pipewire.conf.d/vrcpilot-mic.conf`` is
  the source of truth and survives restarts.
* **Immediate runtime load** (opt-in via ``runtime_load=True``):
  a ``pulsectl`` ``module_load`` so the sink works in the current
  session. Failures degrade to a warning on
  :attr:`RegisterResult.runtime_warning` and never mask a successful
  config write.

``pulsectl`` is imported lazily inside :func:`open_pulse_control` --
the single seam every caller (``register`` / ``unregister`` /
``status``) funnels through, so tests patch one symbol.

Raises ``ImportError`` if imported off-Linux.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
    raise ImportError("vrcpilot.mic.linux is Linux-only")

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
#:
#: Written in PipeWire 1.0+ syntax: the standalone
#: ``libpipewire-module-null-sink`` module was removed and replaced by
#: ``module-adapter`` driving the built-in ``support.null-audio-sink``
#: factory. The older ``context.modules`` form aborts daemon start-up
#: on 1.0+ (``mandatory module ... No such file or directory`` → exit
#: 254), so this fragment must not regress.
_PIPEWIRE_CONF: Final[str] = """\
context.objects = [
    {   factory = adapter
        args = {
            factory.name     = support.null-audio-sink
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
#: ``src/vrcpilot/speaker/linux.py``'s style).
_NULL_SINK_ARGS: Final[str] = (
    f"sink_name={VIRTUAL_MIC_SINK_NAME} "
    "sink_properties=device.description=VRCPilot_Virtual_Mic "
    "rate=48000 channels=2 format=float32le channel_map=front-left,front-right"
)


@dataclass(frozen=True)
class RegisterResult:
    """Outcome of :func:`register_virtual_mic`.

    ``created_config`` is ``False`` if the file already had the expected
    contents. ``runtime_loaded`` is ``False`` both when skipped and when
    the load failed -- ``runtime_warning`` is ``None`` for the skip case
    and a human-readable string for the failure case.
    """

    config_path: Path
    created_config: bool
    runtime_loaded: bool
    runtime_warning: str | None


def config_path() -> Path:
    """Absolute path of the PipeWire config fragment.

    Honours ``$XDG_CONFIG_HOME`` with ``~/.config`` as the XDG fallback.
    Public so ``vrcpilot linux-mic status`` can surface the location.
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
    through, so tests patch this one symbol. ``pulsectl`` is imported
    lazily so hosts without it can still write the persistent config.
    ``client_name`` shows up in ``pactl list short clients`` to
    distinguish the entry point in PulseAudio diagnostics.

    Raises ``ImportError`` when ``pulsectl`` is not installed.
    """
    # ``pulsectl`` is a Linux-only conditional dependency
    # (``sys_platform == 'linux'`` in pyproject.toml); silence the
    # unknown-type fallout from its missing inline annotations.
    from pulsectl import (  # pyright: ignore[reportMissingTypeStubs]
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
        # ``_reset_stale_modules`` in ``src/vrcpilot/speaker/linux.py``.
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

    Set ``runtime_load=False`` for headless CI / chroot setups without
    a PipeWire daemon -- the persistent config still writes. Runtime
    failures surface via :attr:`RegisterResult.runtime_warning` rather
    than raising; filesystem failures still propagate as ``OSError``.
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

    Returns ``True`` iff anything was actually removed.
    """
    path = config_path()
    removed_file = False
    if path.exists():
        path.unlink()
        removed_file = True

    runtime_unloaded = _runtime_unload_null_sink()
    return removed_file or runtime_unloaded
