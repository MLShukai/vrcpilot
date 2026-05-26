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


# ---------------------------------------------------------------------------
# Hermetic: suffixed register
# ---------------------------------------------------------------------------
#
# A ``suffix`` argument lets multiple virtual mics coexist (e.g. one
# for the user and one for a bot avatar on the same host). The
# persistent-config layer is the source of truth, so the contract that
# matters end-to-end is:
#
# * Each suffix writes a distinct ``vrcpilot-mic[-<suffix>].conf`` file.
# * The conf body advertises the per-suffix sink name + description so
#   PipeWire reconstructs the right sink on restart.
# * The default-suffix call continues to write the bare
#   ``vrcpilot-mic.conf`` (backward compat).
# * Invalid suffixes raise before any filesystem side-effect.
#
# The runtime-load half is exercised by the existing hermetic tests
# above via the ``no_pulsectl`` seam; the new tests pass
# ``runtime_load=False`` for the same hermeticity reason.

import re  # noqa: E402

_PIPEWIRE_KV = re.compile(
    r"""
    {key}\s*=\s*                    # key + '='
    (?:"(?P<dq>[^"]+)"              # double-quoted value
       |'(?P<sq>[^']+)'             # single-quoted value
       |(?P<bare>[^\s"',\]]+))      # or bare token
    """,
    re.VERBOSE,
)


def _extract_value(contents: str, key: str) -> str | None:
    """Pull a single PipeWire ``key = value`` value out of ``contents``.

    Accepts the bare / single-quoted / double-quoted forms PipeWire
    allows, with any whitespace between the key and ``=``. Returns
    ``None`` if the key is absent so callers can distinguish "missing"
    from "present but unexpected value" in their assertions.
    """
    pattern = re.compile(
        _PIPEWIRE_KV.pattern.replace("{key}", re.escape(key)),
        re.VERBOSE,
    )
    match = pattern.search(contents)
    if match is None:
        return None
    return match.group("dq") or match.group("sq") or match.group("bare")


class TestSuffixedRegister:
    def test_register_with_suffix_writes_suffixed_config_path(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # The persistent filename is the only thing that lets a second
        # ``register`` call coexist with the first; if the suffix did
        # not flow into the filename, the second call would overwrite
        # the first and silently merge the two virtual mics into one.
        result = mic_linux.register_virtual_mic(suffix="alt", runtime_load=False)
        assert result.config_path.name == "vrcpilot-mic-alt.conf"
        assert result.config_path.exists()

    def test_register_with_suffix_writes_suffixed_sink_in_conf(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # On restart, PipeWire rebuilds the sink from the conf body,
        # not from the filename. The body must therefore carry the
        # per-suffix ``node.name`` and ``node.description`` -- otherwise
        # after a reboot every suffix would resurrect as the bare
        # ``VRCPilotMic`` and collide on the control plane.
        result = mic_linux.register_virtual_mic(suffix="alt", runtime_load=False)
        contents = result.config_path.read_text()

        assert _extract_value(contents, "node.name") == "VRCPilotMic_alt"
        assert (
            _extract_value(contents, "node.description") == "VRCPilot_Virtual_Mic_alt"
        )

    def test_register_default_and_suffixed_coexist(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # Two register calls with different suffixes must produce two
        # distinct files on disk so the user actually gets two virtual
        # mics. This is the core motivation of the whole suffix
        # feature, so pin it explicitly.
        mic_linux.register_virtual_mic(suffix="", runtime_load=False)
        mic_linux.register_virtual_mic(suffix="alt", runtime_load=False)

        default_path = mic_linux.config_path(suffix="")
        suffixed_path = mic_linux.config_path(suffix="alt")
        assert default_path.exists()
        assert suffixed_path.exists()
        assert default_path != suffixed_path

    @pytest.mark.parametrize("bad_suffix", ["bad name", "../etc", "a/b", "a;b"])
    def test_register_invalid_suffix_raises_value_error(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
        bad_suffix: str,
    ) -> None:
        # Validation belongs in front of the filesystem side-effect:
        # if a typo like ``"../etc"`` slipped through, the resolved
        # filename could land outside ``pipewire.conf.d/`` and the
        # ``unregister`` round-trip would not find it. Failing fast
        # before any write is the safe path.
        with pytest.raises(ValueError):
            mic_linux.register_virtual_mic(suffix=bad_suffix, runtime_load=False)


# ---------------------------------------------------------------------------
# Hermetic: suffixed unregister
# ---------------------------------------------------------------------------


class TestSuffixedUnregister:
    def test_unregister_default_leaves_suffixed_config_alone(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # **Critical isolation guarantee**: removing the default mic
        # must not touch sibling suffixed mics. Without this, a user
        # who registered both a default and an ``alt`` mic could lose
        # the ``alt`` one by running ``linux-mic unregister``. Pin it.
        mic_linux.register_virtual_mic(suffix="", runtime_load=False)
        mic_linux.register_virtual_mic(suffix="alt", runtime_load=False)

        removed = mic_linux.unregister_virtual_mic(suffix="")

        assert removed is True
        assert not mic_linux.config_path(suffix="").exists()
        assert mic_linux.config_path(suffix="alt").exists()

    def test_unregister_specific_suffix_removes_only_that_file(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # Mirror image of the previous test: unregistering ``alt`` must
        # leave the default mic intact. Both directions are guarded
        # so a regression on either side fails loudly.
        mic_linux.register_virtual_mic(suffix="", runtime_load=False)
        mic_linux.register_virtual_mic(suffix="alt", runtime_load=False)

        removed = mic_linux.unregister_virtual_mic(suffix="alt")

        assert removed is True
        assert not mic_linux.config_path(suffix="alt").exists()
        assert mic_linux.config_path(suffix="").exists()

    def test_unregister_returns_false_for_unknown_suffix(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # No-op unregister is a valid idempotent outcome; the boolean
        # return is what the CLI uses to decide whether to log
        # "removed". A truthy return when nothing existed would
        # mislead users into thinking a stale install was cleaned up.
        removed = mic_linux.unregister_virtual_mic(suffix="never-registered")
        assert removed is False


# ---------------------------------------------------------------------------
# Hermetic: iter_registered_suffixes
# ---------------------------------------------------------------------------


class TestIterRegisteredSuffixes:
    def test_iter_returns_empty_when_dir_missing(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # On a fresh host the ``pipewire.conf.d/`` directory does not
        # exist yet; the listing path must treat that as "nothing
        # registered" rather than raising ``FileNotFoundError``.
        assert mic_linux.iter_registered_suffixes() == []

    def test_iter_lists_default_only(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # The default registration is canonically represented as the
        # empty-string suffix in the listing so callers do not have
        # to special-case "default vs. named" in their UI loops.
        mic_linux.register_virtual_mic(suffix="", runtime_load=False)
        assert mic_linux.iter_registered_suffixes() == [""]

    def test_iter_lists_default_and_suffixed_sorted(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # Deterministic ordering (empty first, then ASCII-sorted) so
        # the CLI's ``linux-mic list`` output is stable across runs
        # and across hosts. Pin both halves of the order so a sloppy
        # ``sorted(...)`` over the bare list (which would put ""
        # first by default) keeps working but a switch to set
        # iteration would fail this test.
        mic_linux.register_virtual_mic(suffix="", runtime_load=False)
        mic_linux.register_virtual_mic(suffix="bot", runtime_load=False)
        mic_linux.register_virtual_mic(suffix="alt", runtime_load=False)

        assert mic_linux.iter_registered_suffixes() == ["", "alt", "bot"]

    def test_iter_ignores_unrelated_files(
        self,
        isolate_config: Path,
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        # The conf dir is shared with PipeWire's own fragments and
        # user-installed ones; the listing must only pick up files
        # whose name matches the ``vrcpilot-mic[-<suffix>].conf``
        # pattern. A naive ``glob("*.conf")`` would surface noise from
        # neighbouring tools and trip the suffix-name validator.
        mic_linux.register_virtual_mic(suffix="", runtime_load=False)
        conf_dir = isolate_config / "pipewire" / "pipewire.conf.d"
        (conf_dir / "other.conf").write_text("# unrelated fragment\n")

        assert mic_linux.iter_registered_suffixes() == [""]


# ---------------------------------------------------------------------------
# Public-API contract: RegisterResult.suffix
# ---------------------------------------------------------------------------


class TestRegisterResultSuffix:
    """Contract pin: ``RegisterResult.suffix`` is part of the public API.

    The CLI prints ``result.suffix`` in user-facing summaries and the
    e2e scenarios consume it to decide which sink to play into; both
    paths break if the field is renamed or dropped. Pin it explicitly
    so a refactor that drops the field fails loudly here instead of
    surfacing later as a runtime ``AttributeError``.
    """

    def test_register_result_suffix_empty_for_default(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        result = mic_linux.register_virtual_mic(runtime_load=False)
        assert result.suffix == ""

    def test_register_result_suffix_matches_argument(
        self,
        isolate_config: Path,  # noqa: ARG002
        no_pulsectl: None,  # noqa: ARG002
    ) -> None:
        result = mic_linux.register_virtual_mic(suffix="alt", runtime_load=False)
        assert result.suffix == "alt"


# ---------------------------------------------------------------------------
# Cross-check: filename mapping stays in lock-step with base helper
# ---------------------------------------------------------------------------


class TestConfigPathFilenameMatchesBaseHelper:
    """The persistent-config filename for a given suffix is derived by
    :func:`vrcpilot.mic.linux.config_filename_for`.

    If the linux module ever computes the filename inline and drifts
    from that helper, the listing and the writer would disagree on which
    files belong to vrcpilot. Pin the equivalence directly.
    """

    @pytest.mark.parametrize("suffix", ["", "alt", "bot"])
    def test_config_path_filename_for_suffix(
        self,
        isolate_config: Path,  # noqa: ARG002
        suffix: str,
    ) -> None:
        path = mic_linux.config_path(suffix=suffix)
        assert path.name == config_filename_for(suffix)
        assert path.name.endswith(".conf")


# ---------------------------------------------------------------------------
# Suffix naming helpers (sink / description / config-filename)
# ---------------------------------------------------------------------------
#
# These three pure functions are the contract that lets multiple virtual
# mics coexist without name collisions. They are consumed by:
#
# * ``vrcpilot.mic.linux.register_virtual_mic(suffix=...)`` to derive
#   the PipeWire sink name, the PulseAudio description, and the
#   ``pipewire.conf.d/`` fragment filename.
# * The CLI's ``linux-mic register --suffix`` path so what the user
#   types lines up with what ``pactl list`` reports afterwards.
#
# Drift between any two of these three would cause the persistent
# config and the runtime sink (or the CLI display) to refer to
# different names -- a regression that is silent until a user tries to
# select the second mic. The tests below pin all three together.

from vrcpilot.mic.linux import (  # noqa: E402
    config_filename_for,
    description_for,
    sink_name_for,
)


class TestSinkNameFor:
    def test_empty_suffix_returns_bare_canonical_name(self) -> None:
        # Backward-compat with the original single-sink design: the
        # default suffix must continue to produce ``"VRCPilotMic"`` so
        # existing config files and OSC presets keep working.
        assert sink_name_for("") == "VRCPilotMic"

    def test_alphabetic_suffix_is_appended_with_underscore_separator(self) -> None:
        assert sink_name_for("alt") == "VRCPilotMic_alt"

    def test_alphanumeric_with_dash_and_underscore_is_preserved_verbatim(
        self,
    ) -> None:
        # ``_`` and ``-`` are the only non-alphanumerics that survive
        # normalisation -- they appear in user-chosen profile names and
        # must round-trip exactly so ``pactl list`` matches.
        assert sink_name_for("foo_bar-baz") == "VRCPilotMic_foo_bar-baz"

    @pytest.mark.parametrize(
        "bad_suffix",
        ["bad name", "a/b", "a;b", "a.b", "a:b", "a$b"],
    )
    def test_invalid_characters_raise_value_error(self, bad_suffix: str) -> None:
        # The validation guard is the only thing stopping a typo from
        # silently producing a different sink name than the caller
        # asked for (and the only thing stopping shell-special chars
        # from being injected into the PulseAudio ``module_load``
        # argument string at the call site downstream).
        with pytest.raises(ValueError):
            sink_name_for(bad_suffix)


class TestDescriptionFor:
    def test_empty_suffix_returns_bare_canonical_description(self) -> None:
        # Underscores instead of spaces so the value stays a single
        # PulseAudio token in ``module_load`` arguments (matches the
        # speaker backend's style).
        assert description_for("") == "VRCPilot_Virtual_Mic"

    def test_suffix_is_appended_with_underscore_separator(self) -> None:
        assert description_for("alt") == "VRCPilot_Virtual_Mic_alt"


class TestConfigFilenameFor:
    def test_empty_suffix_returns_bare_canonical_filename(self) -> None:
        # The bare filename must stay ``vrcpilot-mic.conf`` so existing
        # installs are recognised by ``is_registered()`` after the
        # suffix feature ships (no migration required).
        assert config_filename_for("") == "vrcpilot-mic.conf"

    def test_suffix_is_appended_with_hyphen_separator(self) -> None:
        # Hyphen (not underscore) for filenames so they remain a single
        # shell-friendly token and visually match ``vrcpilot-mic.conf``.
        assert config_filename_for("alt") == "vrcpilot-mic-alt.conf"
