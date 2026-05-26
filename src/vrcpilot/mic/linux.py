"""Linux PipeWire virtual-mic registration.

Installs one or more ``VRCPilotMic`` null-sinks that
:class:`vrcpilot.mic.Mic` writes float32 PCM into and VRChat reads via
``Monitor of <sink>``. Two planes:

* **Persistence**: a PipeWire config fragment under
  ``$XDG_CONFIG_HOME/pipewire/pipewire.conf.d/vrcpilot-mic[-<suffix>].conf``
  is the source of truth and survives restarts.
* **Immediate runtime load** (opt-in via ``runtime_load=True``):
  a ``pulsectl`` ``module_load`` so the sink works in the current
  session. Failures degrade to a warning on
  :attr:`RegisterResult.runtime_warning` and never mask a successful
  config write.

Every public function accepts a ``suffix`` keyword. The default empty
suffix preserves the legacy single-sink behaviour; non-empty suffixes
allow callers to register additional sinks side-by-side (e.g. a
secondary ``VRCPilotMic_alt`` for a second VRChat instance) without
clobbering the production one.

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
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vrcpilot.mic.base import (
    _normalize_suffix,  # pyright: ignore[reportPrivateUsage]
    config_filename_for,
    description_for,
    sink_name_for,
)

_logger = logging.getLogger(__name__)

#: Pattern used by :func:`iter_registered_suffixes` to recover the
#: suffix from a config filename. Group 1 is ``None`` for the
#: suffix-less ``vrcpilot-mic.conf``.
_CONFIG_FILENAME_RE = re.compile(r"^vrcpilot-mic(?:-(.+))?\.conf$")


def _build_pipewire_conf(suffix: str = "") -> str:
    """PipeWire 1.0+ config fragment for the ``suffix`` null-sink.

    Written in the ``context.objects`` / ``adapter`` +
    ``support.null-audio-sink`` form. The older
    ``libpipewire-module-null-sink`` module was removed in PipeWire 1.0
    and a config that still references it aborts daemon start-up
    (exit 254), so this fragment must not regress.

    Mirrors the runtime ``module_load`` arguments so PipeWire rebuilds
    the same sink after a restart / re-login.
    """
    sink_name = sink_name_for(suffix)
    description = description_for(suffix)
    return f"""\
context.objects = [
    {{   factory = adapter
        args = {{
            factory.name     = support.null-audio-sink
            node.name        = "{sink_name}"
            node.description = "{description}"
            media.class      = "Audio/Sink"
            audio.position   = [ FL FR ]
            audio.rate       = 48000
            monitor.channel-volumes = true
        }}
    }}
]
"""


def _build_null_sink_args(suffix: str = "") -> str:
    """``module-null-sink`` argument string for the ``suffix`` sink.

    PipeWire accepts PulseAudio-style ``module-null-sink`` args via
    libpulse; ``device.description`` uses underscores so the value
    stays a single PulseAudio token (matches the persistent fragment
    and ``src/vrcpilot/speaker/linux.py``'s style).
    """
    sink_name = sink_name_for(suffix)
    description = description_for(suffix)
    return (
        f"sink_name={sink_name} "
        f"sink_properties=device.description={description} "
        "rate=48000 channels=2 format=float32le channel_map=front-left,front-right"
    )


@dataclass(frozen=True)
class RegisterResult:
    """Outcome of :func:`register_virtual_mic`.

    ``created_config`` is ``False`` if the file already had the expected
    contents. ``runtime_loaded`` is ``False`` both when skipped and when
    the load failed -- ``runtime_warning`` is ``None`` for the skip case
    and a human-readable string for the failure case. ``suffix`` is the
    normalised suffix that was registered (empty for the default sink).
    """

    config_path: Path
    created_config: bool
    runtime_loaded: bool
    runtime_warning: str | None
    suffix: str


def config_path(*, suffix: str = "") -> Path:
    """Absolute path of the PipeWire config fragment for ``suffix``.

    Honours ``$XDG_CONFIG_HOME`` with ``~/.config`` as the XDG fallback.
    Public so ``vrcpilot linux-mic status`` can surface the location.
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".config"
    return root / "pipewire" / "pipewire.conf.d" / config_filename_for(suffix)


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


@contextmanager
def _pulse_session(client_name: str) -> Iterator[Any]:
    """Yield an open ``pulsectl.Pulse`` and always close it on exit.

    Centralises the ``open_pulse_control`` -> ``try / finally:
    pulse.close()`` boilerplate that ``_runtime_load_null_sink`` and
    ``_runtime_unload_null_sink`` share. ``ImportError`` (pulsectl
    missing) and any control-plane open failure propagate so callers
    can map them to their own warning strings; ``pulse.close()``
    failures inside the ``finally`` are logged and swallowed because
    the work is already done by the time we reach them.
    """
    pulse = open_pulse_control(client_name)
    try:
        yield pulse
    finally:
        try:
            pulse.close()  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("pulse close failed: %s", exc)


def is_registered(*, suffix: str = "") -> bool:
    """Whether the persistent PipeWire config fragment is in place."""
    return config_path(suffix=suffix).exists()


def iter_registered_suffixes() -> list[str]:
    """List the suffixes currently registered on disk.

    Scans ``pipewire.conf.d/`` for ``vrcpilot-mic*.conf`` fragments and
    extracts the suffix from each filename. The empty suffix (the
    default sink) sorts first; the remainder is in lexicographic order
    so callers get a stable enumeration. Returns ``[]`` if the config
    directory does not exist yet.
    """
    directory = config_path().parent
    if not directory.exists():
        return []

    # Group 1 is ``None`` for the bare ``vrcpilot-mic.conf`` and the
    # regex's quantifier guarantees a non-empty capture otherwise, so
    # ``or ""`` collapses the two cases cleanly.
    suffixes = {
        match.group(1) or ""
        for entry in directory.glob("vrcpilot-mic*.conf")
        if (match := _CONFIG_FILENAME_RE.match(entry.name)) is not None
    }
    # Empty suffix first, then remaining suffixes in lexicographic
    # order so callers (CLI listings, e2e enumerations) get a stable
    # ordering across runs and filesystems.
    return sorted(suffixes, key=lambda s: (s != "", s))


def _write_config(path: Path, contents: str) -> bool:
    """Write ``contents`` to ``path``; ``True`` iff the file actually changed.

    Idempotent on the byte level so re-running ``register`` does not
    perturb the file's mtime when nothing has changed -- which keeps
    PipeWire's config-reload watchers quiet on no-op invocations.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == contents:
        return False
    path.write_text(contents)
    return True


def _unload_matching_null_sinks(pulse: Any, *, sink_name: str) -> int:
    """Unload every ``module-null-sink`` bound to ``sink_name``.

    Shared between ``register`` (stale-cleanup before a fresh load) and
    ``unregister`` (full teardown) so the matching predicate stays
    canonical. Per-entry failures are logged and treated as "this entry
    not unloaded"; this function itself never raises.

    The match must be exact on ``sink_name``: a substring search would
    let ``VRCPilotMic`` accidentally unload ``VRCPilotMic_alt`` (or
    vice versa). Pulse's ``module-null-sink`` argument string always
    contains ``sink_name=<name> `` with a trailing space before the
    next key, so we append a trailing space to the argument we test
    against to make the boundary explicit even when ``sink_name=...``
    happens to be the last token.
    """
    try:
        modules: list[Any] = pulse.module_list()  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    except Exception as exc:  # noqa: BLE001
        _logger.warning("module_list failed: %s", exc)
        return 0

    needle = f"sink_name={sink_name} "
    unloaded = 0
    for module in modules:  # pyright: ignore[reportUnknownVariableType]
        module_obj: object = module
        name = getattr(module_obj, "name", None)
        raw_arg = getattr(module_obj, "argument", None) or ""
        arg = raw_arg.strip() + " "
        if name != "module-null-sink" or needle not in arg:
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


def _runtime_load_null_sink(*, suffix: str = "") -> str | None:
    """Load (or reload) the ``suffix`` null-sink via ``pulsectl``.

    Returns ``None`` on success or a human-readable warning string on
    failure (missing ``pulsectl``, control-plane error, etc.) -- the
    caller surfaces it via :attr:`RegisterResult.runtime_warning`.
    """
    try:
        with _pulse_session("vrcpilot-mic-register") as pulse:
            sink_name = sink_name_for(suffix)
            # Re-runs must not stack two null-sinks; mirrors
            # ``_reset_stale_modules`` in ``src/vrcpilot/speaker/linux.py``.
            _unload_matching_null_sinks(pulse, sink_name=sink_name)
            try:
                pulse.module_load(  # pyright: ignore[reportUnknownMemberType]
                    "module-null-sink", _build_null_sink_args(suffix)
                )
            except Exception as exc:  # noqa: BLE001
                msg = (
                    "pulsectl module_load failed; the persistent config was "
                    "written but the sink will not be available until PipeWire "
                    f"restarts ({exc})"
                )
                _logger.warning(msg)
                return msg
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

    return None


def register_virtual_mic(
    *, suffix: str = "", runtime_load: bool = True
) -> RegisterResult:
    """Persist a ``VRCPilotMic`` null-sink and (optionally) load it now.

    ``suffix`` allows callers to register additional sinks alongside
    the default one without colliding on sink name, filename, or
    runtime module; an empty suffix preserves the legacy single-sink
    layout. Set ``runtime_load=False`` for headless CI / chroot setups
    without a PipeWire daemon -- the persistent config still writes.
    Runtime failures surface via :attr:`RegisterResult.runtime_warning`
    rather than raising; filesystem failures still propagate as
    ``OSError`` and invalid suffixes raise ``ValueError`` via
    :func:`_normalize_suffix`.
    """
    normalized = _normalize_suffix(suffix)
    path = config_path(suffix=normalized)
    created_config = _write_config(path, _build_pipewire_conf(normalized))

    if not runtime_load:
        return RegisterResult(
            config_path=path,
            created_config=created_config,
            runtime_loaded=False,
            runtime_warning=None,
            suffix=normalized,
        )

    warning = _runtime_load_null_sink(suffix=normalized)
    return RegisterResult(
        config_path=path,
        created_config=created_config,
        runtime_loaded=warning is None,
        runtime_warning=warning,
        suffix=normalized,
    )


def _runtime_unload_null_sink(*, suffix: str = "") -> bool:
    """Unload any live ``suffix`` null-sinks; ``True`` iff any matched.

    Missing ``pulsectl`` or control-plane errors are logged and treated
    as "nothing unloaded" -- this is unregister's runtime half, not the
    source of truth, so a failure here never blocks the config delete.
    """
    try:
        with _pulse_session("vrcpilot-mic-unregister") as pulse:
            count = _unload_matching_null_sinks(pulse, sink_name=sink_name_for(suffix))
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
    return count > 0


def unregister_virtual_mic(*, suffix: str = "") -> bool:
    """Remove the persistent config and unload the runtime sink for ``suffix``.

    Default empty suffix targets the legacy ``VRCPilotMic`` sink; a
    non-empty suffix scopes the teardown to that single
    ``VRCPilotMic_<suffix>`` and leaves other registered sinks alone.
    Returns ``True`` iff anything was actually removed (file deleted,
    runtime module unloaded, or both). Invalid suffixes raise
    ``ValueError`` via :func:`_normalize_suffix`.
    """
    normalized = _normalize_suffix(suffix)
    path = config_path(suffix=normalized)
    removed_file = False
    if path.exists():
        path.unlink()
        removed_file = True

    runtime_unloaded = _runtime_unload_null_sink(suffix=normalized)
    return removed_file or runtime_unloaded
