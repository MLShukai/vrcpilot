"""Linux PipeWire virtual mic registration.

Registers a persistent ``VRCPilotMic`` null-sink so that
:class:`vrcpilot.mic.Mic` can write float32 PCM into it. VRChat then
picks ``Monitor of VRCPilotMic`` as its mic input -- the same sink
serves as the playback destination for vrcpilot and as the recording
source for VRChat.

The implementation has two planes:

* **Persistence**: a PipeWire config fragment is written to
  ``$XDG_CONFIG_HOME/pipewire/pipewire.conf.d/vrcpilot-mic.conf`` (or
  ``~/.config/...`` if ``XDG_CONFIG_HOME`` is unset). After a
  ``systemctl --user restart pipewire`` or re-login PipeWire picks the
  sink back up automatically.
* **Immediate runtime load**: ``pulsectl.Pulse.module_load`` loads the
  same ``module-null-sink`` so the user does not have to restart
  PipeWire before the first session. The runtime step is opt-in via
  the ``runtime_load`` keyword (default ``True``) and degrades to a
  warning on failure rather than raising -- the persistent config is
  the source of truth.

``pulsectl`` is imported lazily inside :func:`open_pulse_control` so a
missing ``pulsectl`` install only blocks the runtime-load step and not
the config write. The same helper is the single seam every caller
(``register`` / ``unregister`` / ``status``) goes through so unit tests
can patch one symbol and cover all three code paths.
"""

from __future__ import annotations

import sys

if sys.platform != "linux":
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
        created_config: ``True`` if the call wrote the file (``False``
            if the file already existed with the expected contents).
        runtime_loaded: ``True`` if the immediate ``pulsectl`` load
            succeeded; ``False`` if it was skipped via
            ``runtime_load=False`` or failed (see
            :attr:`runtime_warning`).
        runtime_warning: Human-readable description of the runtime-load
            failure, or ``None`` if no failure occurred.
    """

    config_path: Path
    created_config: bool
    runtime_loaded: bool
    runtime_warning: str | None


def config_path() -> Path:
    """Return the absolute path of the PipeWire config fragment.

    Honours ``$XDG_CONFIG_HOME`` per the XDG Base Directory Spec; falls
    back to ``~/.config`` when the variable is unset or empty. Public
    because the ``vrcpilot linux-mic status`` CLI action surfaces the
    persisted-config location to the user, and per the
    ``feedback_private_module_convention`` rule any symbol that has
    direct unit tests must not carry a ``_`` prefix.
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".config"
    return root / "pipewire" / "pipewire.conf.d" / _CONF_FILENAME


def open_pulse_control(client_name: str = "vrcpilot-mic") -> Any:
    """Construct the ``pulsectl.Pulse`` control connection.

    Single seam every PulseAudio-touching path (``register`` /
    ``unregister`` / ``status``) uses. The import is local so installs
    without ``pulsectl`` (e.g. minimal CI containers) still get to
    write the persistent config -- the missing dependency is surfaced
    as a runtime warning instead of an import error.

    Tests substitute this symbol via
    ``mocker.patch.object(mic_linux, "open_pulse_control", ...)`` and
    return a duck-typed :class:`tests.fakes.FakePulse`. ``client_name``
    is forwarded so each entry point can identify itself in
    ``pactl list short clients``.
    """
    from pulsectl import (  # pyright: ignore[reportMissingTypeStubs]
        Pulse,
    )

    return Pulse(client_name)  # pyright: ignore[reportUnknownVariableType]


def is_registered() -> bool:
    """Return whether the persistent config fragment exists."""
    return config_path().exists()


def _write_config(path: Path) -> bool:
    """Write the config fragment, returning ``True`` if the file changed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == _PIPEWIRE_CONF:
        return False
    path.write_text(_PIPEWIRE_CONF)
    return True


def _unload_matching_null_sinks(pulse: Any) -> int:
    """Unload every ``module-null-sink`` whose ``argument`` targets the sink.

    Walks ``pulse.module_list()`` once, looking for entries whose
    ``name`` is ``"module-null-sink"`` and whose ``argument`` carries
    ``sink_name=<VIRTUAL_MIC_SINK_NAME>``, and calls
    ``pulse.module_unload(index)`` on each. Returns the number of
    successful unloads so callers can decide whether anything actually
    changed.

    Both ``register`` (stale-cleanup before a fresh load) and
    ``unregister`` (full teardown) need this exact filter+unload
    sequence; centralising it keeps the matching predicate canonical
    and ensures both code paths log identical warnings on the same
    failures. Failures inside ``module_list`` / ``module_unload`` are
    logged and treated as "this entry not unloaded" -- the function
    never raises.
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

    Returns ``None`` on success and a human-readable warning string on
    failure (missing ``pulsectl``, control plane error, etc.). The
    caller surfaces the warning through :attr:`RegisterResult.runtime_warning`.
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
        # Unload any stale VRCPilotMic null-sink so a re-run never
        # stacks two; mirrors ``_reset_stale_modules`` in
        # ``src/vrcpilot/speaker/pipewire.py``. The return value is
        # discarded because the fresh load happens unconditionally.
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
        runtime_load: When ``True`` (default), additionally invoke
            ``pulsectl.Pulse.module_load`` so the sink is usable
            immediately. Pass ``False`` to write only the persistent
            config (useful for headless CI / chroot setups where no
            PipeWire daemon is running).

    Returns:
        A :class:`RegisterResult` describing what was done. A runtime
        failure is reported via
        :attr:`RegisterResult.runtime_warning` rather than raised; the
        persistent config is always written successfully or an
        :class:`OSError` is propagated.
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
    """Unload any ``VRCPilotMic`` null-sinks currently loaded in PipeWire.

    Returns ``True`` if at least one matching module was unloaded.
    Failures (missing ``pulsectl``, control-plane error) are logged
    and treated as "nothing unloaded".
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

    Returns ``True`` if anything was actually removed (config file
    deleted, runtime module unloaded, or both). ``False`` when neither
    artefact existed.
    """
    path = config_path()
    removed_file = False
    if path.exists():
        path.unlink()
        removed_file = True

    runtime_unloaded = _runtime_unload_null_sink()
    return removed_file or runtime_unloaded
