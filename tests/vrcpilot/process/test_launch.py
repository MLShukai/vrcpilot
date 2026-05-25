"""Tests for :mod:`vrcpilot.process.launch`.

What is covered here vs. elsewhere:

* **Pure argv / config helpers** (``OscConfig``, ``build_vrchat_launch_args``,
  ``build_launch_command``, ``validate_launch_args``) are unit-tested
  directly with no mocks.
* **The orchestrating ``launch()`` function** spawns a real subprocess
  (``subprocess.Popen``) and polls ``psutil`` for new PIDs. Both seams
  are 3rd-party surfaces the test policy forbids mocking. End-to-end
  argv / spawn / wait behaviour is therefore covered by
  ``tests/e2e/``.

The ``VRChatAlreadyRunningError`` precondition for ``via_steam=True``
similarly requires ``find_pids()`` to observe a real ``VRChat.exe``
process; that path is e2e-only.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from tests.helpers import only_linux, only_windows
from vrcpilot.process import VRCHAT_STEAM_APP_ID, OscConfig, build_launch_command
from vrcpilot.process.launch import (
    build_vrchat_launch_args,
    validate_launch_args,
)


class TestOscConfig:
    """``OscConfig`` formats VRChat's ``--osc=<in>:<ip>:<out>`` flag."""

    def test_default_emits_documented_ports(self):
        # Spec: in=9000, out=127.0.0.1:9001 are the documented defaults.
        # If a future change moves the defaults the launch flag layout
        # breaks for every caller relying on the documented behaviour.
        assert OscConfig().to_launch_arg() == "--osc=9000:127.0.0.1:9001"

    def test_custom_values_render_in_in_ip_out_order(self):
        cfg = OscConfig(in_port=10000, out_ip="192.168.1.10", out_port=10001)

        assert cfg.to_launch_arg() == "--osc=10000:192.168.1.10:10001"

    def test_is_frozen(self):
        # ``frozen=True`` is part of the API contract: callers may rely
        # on OscConfig values being hashable / cache-safe.
        cfg = OscConfig()

        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.in_port = 1234  # type: ignore[misc]


class TestBuildVrchatLaunchArgs:
    """``build_vrchat_launch_args`` composes VRChat's post-applaunch argv."""

    def test_no_arguments_returns_empty_list(self):
        assert build_vrchat_launch_args() == []

    def test_no_vr_emits_no_vr_flag(self):
        assert build_vrchat_launch_args(no_vr=True) == ["--no-vr"]

    def test_screen_width_alone(self):
        assert build_vrchat_launch_args(screen_width=1280) == [
            "-screen-width",
            "1280",
        ]

    def test_screen_height_alone(self):
        assert build_vrchat_launch_args(screen_height=720) == [
            "-screen-height",
            "720",
        ]

    def test_both_screen_dimensions(self):
        assert build_vrchat_launch_args(screen_width=1280, screen_height=720) == [
            "-screen-width",
            "1280",
            "-screen-height",
            "720",
        ]

    def test_osc_renders_to_single_token(self):
        # OscConfig must render as one ``--osc=...`` token, not two.
        assert build_vrchat_launch_args(osc=OscConfig(in_port=9000)) == [
            "--osc=9000:127.0.0.1:9001"
        ]

    def test_profile_is_single_equals_token(self):
        # VRChat accepts ``--profile=N`` (one token), not ``--profile N``.
        # The exact spelling matters; ``["--profile", "3"]`` would not work.
        assert "--profile=3" in build_vrchat_launch_args(profile=3)

    def test_profile_none_omits_flag(self):
        # No profile -> no flag emitted at all (do not silently default to 0).
        result = build_vrchat_launch_args(profile=None)

        assert not any(a.startswith("--profile") for a in result)

    def test_extra_args_appended_verbatim(self):
        assert build_vrchat_launch_args(extra_args=["--enable-debug-gui"]) == [
            "--enable-debug-gui"
        ]

    def test_argv_order_is_stable(self):
        # Documented order: no_vr -> screen size -> osc -> profile -> extras.
        # Pin the byte layout so e2e harness logs and Steam launch-options
        # captures remain comparable across runs.
        result = build_vrchat_launch_args(
            no_vr=True,
            screen_width=1280,
            screen_height=720,
            osc=OscConfig(),
            profile=2,
            extra_args=["--enable-debug-gui"],
        )

        assert result == [
            "--no-vr",
            "-screen-width",
            "1280",
            "-screen-height",
            "720",
            "--osc=9000:127.0.0.1:9001",
            "--profile=2",
            "--enable-debug-gui",
        ]


class TestBuildLaunchCommand:
    """``build_launch_command`` wraps Steam's ``-applaunch`` argv."""

    def test_basic_shape(self):
        steam = Path("/usr/bin/steam")

        assert build_launch_command(steam, 438100) == [
            str(steam),
            "-applaunch",
            "438100",
        ]

    def test_default_app_id_is_vrchat(self):
        # Default app_id MUST match the documented VRChat constant so
        # callers don't have to repeat it at every call site.
        result = build_launch_command(Path("/usr/bin/steam"))

        assert result[2] == str(VRCHAT_STEAM_APP_ID)

    def test_app_id_is_stringified(self):
        # ``subprocess.Popen`` requires strings; the int must be coerced.
        result = build_launch_command(Path("/usr/bin/steam"), 440)

        assert result[2] == "440"

    def test_vrchat_args_appended_after_app_id(self):
        steam = Path("/usr/bin/steam")

        result = build_launch_command(
            steam, 438100, vrchat_args=["--no-vr", "-screen-width", "1280"]
        )

        assert result == [
            str(steam),
            "-applaunch",
            "438100",
            "--no-vr",
            "-screen-width",
            "1280",
        ]

    def test_none_vrchat_args_does_not_append_anything(self):
        # ``None`` (vs empty list) must produce the same legacy 3-token
        # shape so callers that omit the argument get the legacy command.
        steam = Path("/usr/bin/steam")

        assert build_launch_command(steam, 438100, vrchat_args=None) == [
            str(steam),
            "-applaunch",
            "438100",
        ]


class TestValidateLaunchArgsCrossPlatform:
    """Argument-combo validation that does not depend on ``sys.platform``."""

    def test_defaults_are_accepted(self):
        # No raise expected.
        validate_launch_args(
            via_steam=False, wineprefix=None, proton_path=None, profile=None
        )

    def test_via_steam_alone_is_accepted(self):
        validate_launch_args(
            via_steam=True, wineprefix=None, proton_path=None, profile=None
        )

    def test_zero_profile_is_accepted(self):
        # 0 is a valid VRChat profile number (default profile slot).
        validate_launch_args(
            via_steam=False, wineprefix=None, proton_path=None, profile=0
        )

    def test_negative_profile_rejected(self):
        # VRChat profile slots are non-negative; reject -1 fail-fast at
        # the call site rather than letting Wine see a bogus path.
        with pytest.raises(ValueError, match="non-negative"):
            validate_launch_args(
                via_steam=False, wineprefix=None, proton_path=None, profile=-1
            )

    def test_via_steam_with_wineprefix_rejected(self, tmp_path: Path):
        # Steam route delegates display + Wine setup to Steam; injecting
        # WINEPREFIX would silently bypass that.
        with pytest.raises(ValueError, match="direct-spawn"):
            validate_launch_args(
                via_steam=True,
                wineprefix=tmp_path,
                proton_path=None,
                profile=None,
            )

    def test_via_steam_with_proton_path_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="direct-spawn"):
            validate_launch_args(
                via_steam=True,
                wineprefix=None,
                proton_path=tmp_path,
                profile=None,
            )

    def test_via_steam_with_profile_rejected(self):
        # ``--profile>0`` via Steam belongs in Steam launch options, not
        # in vrcpilot's argv (double-specification risk).
        with pytest.raises(ValueError, match="direct-spawn"):
            validate_launch_args(
                via_steam=True, wineprefix=None, proton_path=None, profile=2
            )

    def test_via_steam_with_profile_zero_is_accepted(self):
        # ``profile=0`` is the new default and aliases the Steam-launched
        # slot on both platforms, so it must remain compatible with
        # ``via_steam=True`` — otherwise the default-args ``launch()`` /
        # ``launch(via_steam=True)`` calls would never validate.
        validate_launch_args(
            via_steam=True, wineprefix=None, proton_path=None, profile=0
        )


class TestValidateLaunchArgsLinux:
    """Linux-only validation paths: wineprefix / proton_path are permitted."""

    @only_linux
    def test_wineprefix_on_linux_is_accepted(self, tmp_path: Path):
        # Linux direct-spawn permits WINEPREFIX overrides (the Wine
        # runtime owns the prefix).
        validate_launch_args(
            via_steam=False,
            wineprefix=tmp_path,
            proton_path=None,
            profile=None,
        )

    @only_linux
    def test_proton_path_on_linux_is_accepted(self, tmp_path: Path):
        validate_launch_args(
            via_steam=False,
            wineprefix=None,
            proton_path=tmp_path,
            profile=None,
        )

    @only_linux
    def test_profile_on_linux_is_accepted(self):
        validate_launch_args(
            via_steam=False, wineprefix=None, proton_path=None, profile=2
        )


@pytest.mark.api_contract
class TestPublicExceptionSurface:
    """The new ``profile=0`` -> Steam compatdata wiring adds a dedicated
    exception class, and the import path must stay stable for callers that want
    to ``except`` it.

    This is a public API contract pin (Hyrum's-law mitigation), not a
    behaviour test: the class name, its inheritance, and its module
    home are all promises to downstream users. Marked
    ``api_contract`` so the rationale for asserting on otherwise-trivial
    ``issubclass`` is explicit.
    """

    def test_VRChatSteamCompatdataNotFoundError_is_importable_from_process(self):
        # ``vrcpilot.process`` is the documented re-export home for
        # process-related exceptions. Callers should never need to
        # reach into ``vrcpilot.process.errors`` or
        # ``vrcpilot.process.launch`` to grab it.
        from vrcpilot.process import VRChatSteamCompatdataNotFoundError

        # ``except RuntimeError`` callers must keep working. The whole
        # process exception family is rooted at ``RuntimeError`` (see
        # ``VRChatNotRunningError`` / ``VRChatLauncherNotFoundError``),
        # and this new sibling must follow the same convention.
        assert issubclass(VRChatSteamCompatdataNotFoundError, RuntimeError)


class TestValidateLaunchArgsWindows:
    """Windows-only validation paths: wineprefix / proton_path are rejected."""

    @only_windows
    def test_wineprefix_on_windows_rejected(self, tmp_path: Path):
        # No Wine on Windows; an accidental WINEPREFIX setting indicates
        # a config copy-paste mistake. Fail fast.
        with pytest.raises(ValueError, match="Linux-only"):
            validate_launch_args(
                via_steam=False,
                wineprefix=tmp_path,
                proton_path=None,
                profile=None,
            )

    @only_windows
    def test_proton_path_on_windows_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Linux-only"):
            validate_launch_args(
                via_steam=False,
                wineprefix=None,
                proton_path=tmp_path,
                profile=None,
            )

    @only_windows
    def test_profile_on_windows_is_accepted(self):
        # ``--profile=N`` is platform-agnostic from VRChat's perspective:
        # Windows VRChat accepts it just as Linux Wine does. Validation
        # must not reject it on Windows.
        validate_launch_args(
            via_steam=False, wineprefix=None, proton_path=None, profile=2
        )


# NOTE: The end-to-end ``launch()`` orchestration (subprocess.Popen
# spawn, env_overrides, pre/post find_pids() diff, the
# VRChatAlreadyRunningError gate for via_steam=True) is covered by
# tests/e2e/ scenarios. Both seams (``subprocess.Popen``,
# ``psutil.process_iter`` for ``find_pids``) are 3rd-party surfaces the
# new test policy forbids mocking, so a unit-style "argv shape" test
# at this layer would have to lie about either seam to run.
