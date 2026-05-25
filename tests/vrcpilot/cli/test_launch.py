"""Tests for :mod:`vrcpilot.cli.launch`.

``vrcpilot launch`` is the argv-to-:func:`vrcpilot.process.launch`
dispatcher. The CLI's responsibilities are:

* Build a Namespace whose flag names match the API kwargs.
* Translate API exceptions to documented exit codes (2 for usage /
  pre-flight, 3 for ``VRChatAlreadyRunningError``).
* Print the PID on success (which we cover via the wait-skipped
  branch -- spawning a real VRChat needs e2e infrastructure).

Real launch on a developer / CI Linux box without ``$DISPLAY`` raises
:class:`VRChatDisplayNotAvailableError` from
:func:`vrcpilot.process.linux.preflight_linux_environment`; the
``--via-steam`` route raises :class:`SteamNotRunningError` from the
same pre-flight when Steam isn't running. Both let us exercise the
``exit 2`` mapping with no mocking. Argparse-only assertions are
exercised through :func:`vrcpilot.cli.build_parser` so they run on
every platform.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vrcpilot.cli import build_parser, main


class TestLaunchArgparse:
    """Argparse plumbing: every documented flag must reach the Namespace."""

    def test_via_steam_defaults_to_false(self):
        ns = build_parser().parse_args(["launch"])
        assert ns.via_steam is False

    def test_via_steam_flag_sets_true(self):
        ns = build_parser().parse_args(["launch", "--via-steam"])
        assert ns.via_steam is True

    def test_app_id_forwarded(self):
        ns = build_parser().parse_args(["launch", "--app-id", "999"])
        assert ns.app_id == 999

    def test_steam_path_forwarded(self, tmp_path: Path):
        steam_path = tmp_path / "steam.exe"
        ns = build_parser().parse_args(["launch", "--steam-path", str(steam_path)])
        assert ns.steam_path == steam_path

    def test_vrchat_launcher_forwarded(self, tmp_path: Path):
        launcher = tmp_path / "launch.exe"
        ns = build_parser().parse_args(["launch", "--vrchat-launcher", str(launcher)])
        assert ns.vrchat_launcher == launcher

    def test_wineprefix_forwarded(self, tmp_path: Path):
        prefix = tmp_path / "prefix"
        ns = build_parser().parse_args(["launch", "--wineprefix", str(prefix)])
        assert ns.wineprefix == prefix

    def test_proton_path_forwarded(self, tmp_path: Path):
        proton = tmp_path / "proton"
        ns = build_parser().parse_args(["launch", "--proton-path", str(proton)])
        assert ns.proton_path == proton

    def test_profile_defaults_to_zero(self):
        # The default ``launch`` invocation must map to the Steam-shared
        # slot (Linux: ``compatdata/<app_id>/pfx``; Windows: VRChat's
        # default profile) so an unflagged CLI run matches what
        # ``--via-steam`` would do.
        ns = build_parser().parse_args(["launch"])
        assert ns.profile == 0

    def test_profile_zero_accepted(self):
        ns = build_parser().parse_args(["launch", "--profile", "0"])
        assert ns.profile == 0

    def test_profile_positive_accepted(self):
        ns = build_parser().parse_args(["launch", "--profile", "3"])
        assert ns.profile == 3

    def test_profile_negative_rejected(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # Custom ``_profile_value`` raises ``ArgumentTypeError`` for
        # negatives; argparse surfaces it as exit 2 with the message
        # in stderr.
        with pytest.raises(SystemExit):
            main(["launch", "--profile", "-1"])
        assert "non-negative" in capsys.readouterr().err

    def test_no_vr_flag(self):
        ns = build_parser().parse_args(["launch", "--no-vr"])
        assert ns.no_vr is True

    def test_screen_dimensions(self):
        ns = build_parser().parse_args(
            ["launch", "--screen-width", "1920", "--screen-height", "1080"]
        )
        assert ns.screen_width == 1920
        assert ns.screen_height == 1080

    def test_osc_inbound_and_outbound(self):
        ns = build_parser().parse_args(
            [
                "launch",
                "--osc-in-port",
                "9100",
                "--osc-out-ip",
                "1.2.3.4",
                "--osc-out-port",
                "9200",
            ]
        )
        assert ns.osc_in_port == 9100
        assert ns.osc_out_ip == "1.2.3.4"
        assert ns.osc_out_port == 9200

    def test_osc_outbound_defaults(self):
        ns = build_parser().parse_args(["launch"])
        # Defaults match the docstring: out-ip 127.0.0.1, out-port 9001.
        assert ns.osc_in_port is None
        assert ns.osc_out_ip == "127.0.0.1"
        assert ns.osc_out_port == 9001

    def test_wait_timeout_forwarded(self):
        ns = build_parser().parse_args(["launch", "--wait-timeout", "0.5"])
        assert ns.wait_timeout == pytest.approx(0.5)


class TestLaunchValidationErrors:
    """Cases where :func:`vrcpilot.process.launch` raises before spawning.

    These exercise the real validation path (``validate_launch_args`` /
    ``preflight_linux_environment``); no subprocess is started.
    """

    def test_via_steam_with_profile_exits_2(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``validate_launch_args`` rejects this combination with
        # ``ValueError``; the CLI maps ``ValueError`` to exit 2.
        assert main(["launch", "--via-steam", "--profile", "1"]) == 2
        assert "vrcpilot:" in capsys.readouterr().err

    def test_via_steam_with_wineprefix_exits_2(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        prefix = tmp_path / "prefix"
        # Direct-spawn-only flag + ``--via-steam`` is rejected by
        # ``validate_launch_args``.
        assert main(["launch", "--via-steam", "--wineprefix", str(prefix)]) == 2
        assert "vrcpilot:" in capsys.readouterr().err


class TestLaunchLinuxPreflight:
    """Real Linux pre-flight branches (no DISPLAY / no Steam)."""

    def test_direct_spawn_without_display_exits_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        if sys.platform != "linux":
            pytest.skip("Linux pre-flight is only run on Linux")
        # Clear both display env vars so pre-flight definitely raises
        # VRChatDisplayNotAvailableError -- regardless of how the host
        # is configured.
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        assert main(["launch", "--wait-timeout", "0"]) == 2
        assert "DISPLAY" in capsys.readouterr().err

    def test_via_steam_without_steam_running_exits_2(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        if sys.platform != "linux":
            pytest.skip("Steam pre-flight only runs on Linux for --via-steam")
        # On a CI host Steam is never running. ``preflight_linux_environment``
        # raises ``SteamNotRunningError`` which the CLI maps to exit 2.
        assert main(["launch", "--via-steam", "--wait-timeout", "0"]) == 2
        assert "Steam" in capsys.readouterr().err
