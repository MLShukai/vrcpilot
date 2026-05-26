"""Tests for :mod:`vrcpilot.cli.linux_mic` (Linux-only).

``vrcpilot linux-mic`` manages the PipeWire null-sink that exposes a
virtual mic to VRChat. The three actions (``register`` / ``unregister``
/ ``status``) talk to ``pulsectl`` + ``soundcard`` + the on-disk
PipeWire config. Real success paths need a working PipeWire daemon,
which we do not bring up in unit tests -- those are deferred to e2e.

What we can cover here without a daemon:

* Argparse plumbing (action required, sub-options resolved).
* ``status`` always returns 0 and prints the documented stable
  vocabulary on stdout even when probes fail (probe errors land on
  stderr, not stdout).
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "linux":
    pytest.skip("vrcpilot.cli.linux_mic is Linux-only", allow_module_level=True)

from vrcpilot.cli import build_parser, main  # noqa: E402


class TestLinuxMicArgparse:
    def test_action_required(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as excinfo:
            main(["linux-mic"])
        assert excinfo.value.code != 0
        assert capsys.readouterr().err != ""

    def test_register_action(self):
        ns = build_parser().parse_args(["linux-mic", "register"])
        assert ns.action == "register"
        assert ns.no_runtime_load is False

    def test_register_no_runtime_load_flag(self):
        ns = build_parser().parse_args(["linux-mic", "register", "--no-runtime-load"])
        assert ns.no_runtime_load is True

    def test_unregister_action(self):
        ns = build_parser().parse_args(["linux-mic", "unregister"])
        assert ns.action == "unregister"

    def test_status_action(self):
        ns = build_parser().parse_args(["linux-mic", "status"])
        assert ns.action == "status"

    # --- suffix / --all argparse plumbing ----------------------------

    def test_register_accepts_suffix_flag(self):
        ns = build_parser().parse_args(["linux-mic", "register", "--suffix", "alt"])
        assert ns.suffix == "alt"

    def test_register_default_suffix_is_empty(self):
        ns = build_parser().parse_args(["linux-mic", "register"])
        assert ns.suffix == ""

    def test_unregister_accepts_suffix_flag(self):
        ns = build_parser().parse_args(["linux-mic", "unregister", "--suffix", "alt"])
        assert ns.suffix == "alt"
        assert ns.all is False

    def test_unregister_accepts_all_flag(self):
        ns = build_parser().parse_args(["linux-mic", "unregister", "--all"])
        assert ns.all is True
        assert ns.suffix == ""

    def test_unregister_suffix_and_all_are_mutually_exclusive(
        self, capsys: pytest.CaptureFixture[str]
    ):
        with pytest.raises(SystemExit) as excinfo:
            build_parser().parse_args(
                ["linux-mic", "unregister", "--suffix", "alt", "--all"]
            )
        assert excinfo.value.code != 0

    def test_status_accepts_suffix_flag(self):
        ns = build_parser().parse_args(["linux-mic", "status", "--suffix", "alt"])
        assert ns.suffix == "alt"
        assert ns.all is False

    def test_status_accepts_all_flag(self):
        ns = build_parser().parse_args(["linux-mic", "status", "--all"])
        assert ns.all is True
        assert ns.suffix == ""

    def test_status_suffix_and_all_are_mutually_exclusive(
        self, capsys: pytest.CaptureFixture[str]
    ):
        with pytest.raises(SystemExit) as excinfo:
            build_parser().parse_args(
                ["linux-mic", "status", "--suffix", "alt", "--all"]
            )
        assert excinfo.value.code != 0


# --- Shared helpers for the suffixed status / register / unregister suites ---


def _patch_status_probes_to_succeed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config_present: bool = True,
    config_dir: str = "/tmp/vrcpilot-fake-pipewire-conf.d",
    runtime_loaded: bool = True,
    soundcard_visible: bool = True,
) -> None:
    """Patch every public seam ``status`` touches.

    Keeps the 3rd-party world (``pulsectl`` / ``soundcard``) out of the
    picture by patching the two private CLI helpers that wrap them; the
    on-disk seams (``is_registered`` / ``config_path``) are replaced
    with deterministic returns so the output vocabulary is fully
    controllable.
    """
    from pathlib import Path

    from vrcpilot.cli import linux_mic as cli_linux_mic
    from vrcpilot.mic import linux as mic_linux

    def fake_is_registered(*, suffix: str = "") -> bool:
        return config_present

    def fake_config_path(*, suffix: str = "") -> Path:
        name = "vrcpilot-mic.conf" if not suffix else f"vrcpilot-mic-{suffix}.conf"
        return Path(config_dir) / name

    def fake_runtime_loaded(sink_name: str) -> tuple[bool, str | None]:
        return runtime_loaded, None

    def fake_soundcard_visible(sink_name: str) -> tuple[bool, str | None]:
        return soundcard_visible, None

    monkeypatch.setattr(mic_linux, "is_registered", fake_is_registered)
    monkeypatch.setattr(mic_linux, "config_path", fake_config_path)
    monkeypatch.setattr(cli_linux_mic, "_runtime_loaded", fake_runtime_loaded)
    monkeypatch.setattr(cli_linux_mic, "_soundcard_visible", fake_soundcard_visible)


class TestLinuxMicStatusSuffixed:
    """``status`` formatting around ``--suffix`` and ``--all``.

    The back-compat pin (no ``suffix:`` line on the empty-suffix default
    path) is load-bearing for downstream scripts that grep for the
    four-line vocabulary; the new suffix / all paths layer on top
    without disturbing it.
    """

    def test_status_default_omits_suffix_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # Back-compat pin: the no-argument default path must NOT emit a
        # leading ``suffix:`` line. Existing scripts grep these four
        # exact line prefixes; adding a header here would break them.
        _patch_status_probes_to_succeed(monkeypatch)

        rc = main(["linux-mic", "status"])

        assert rc == 0
        stdout = capsys.readouterr().out
        assert "suffix:" not in stdout
        # The four canonical lines still appear in order.
        lines = stdout.splitlines()
        assert lines[0].startswith("config:")
        assert lines[1].startswith("config_path:")
        assert lines[2].startswith("runtime:")
        assert lines[3].startswith("soundcard:")

    def test_status_with_suffix_emits_suffix_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # With ``--suffix alt`` the block grows to five lines, led by
        # ``suffix: alt``; the rest of the vocabulary stays identical
        # so a single parser handles both modes.
        _patch_status_probes_to_succeed(monkeypatch)

        rc = main(["linux-mic", "status", "--suffix", "alt"])

        assert rc == 0
        stdout = capsys.readouterr().out
        lines = stdout.splitlines()
        assert lines[0] == "suffix: alt"
        assert lines[1].startswith("config:")
        assert lines[2].startswith("config_path:")
        assert lines[3].startswith("runtime:")
        assert lines[4].startswith("soundcard:")

    def test_status_all_emits_one_block_per_suffix(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``--all`` walks every registered suffix and prints one block
        # per entry, separated by a single blank line. Order is the
        # iteration order returned by ``iter_registered_suffixes`` --
        # tested elsewhere; here we only pin the per-block structure
        # and the blank-line separator.
        from vrcpilot.mic import linux as mic_linux

        _patch_status_probes_to_succeed(monkeypatch)
        monkeypatch.setattr(mic_linux, "iter_registered_suffixes", lambda: ["", "alt"])

        rc = main(["linux-mic", "status", "--all"])

        assert rc == 0
        stdout = capsys.readouterr().out

        # Two blocks separated by exactly one blank line.
        blocks = stdout.split("\n\n")
        assert len(blocks) == 2, (
            f"expected 2 status blocks separated by a blank line; got "
            f"{len(blocks)} blocks. stdout={stdout!r}"
        )

        first_lines = blocks[0].splitlines()
        # Block for the empty suffix still gets a header line so the
        # output is uniformly parseable per-block.
        assert first_lines[0] == "suffix: "
        assert first_lines[1].startswith("config:")
        assert first_lines[2].startswith("config_path:")
        assert first_lines[3].startswith("runtime:")
        assert first_lines[4].startswith("soundcard:")

        second_lines = blocks[1].splitlines()
        assert second_lines[0] == "suffix: alt"
        assert second_lines[1].startswith("config:")
        assert second_lines[2].startswith("config_path:")
        assert second_lines[3].startswith("runtime:")
        assert second_lines[4].startswith("soundcard:")

    def test_status_all_with_empty_config_dir_emits_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # When no fragments exist, ``--all`` must still exit 0 and tell
        # the user where to look: the stdout block carries the absence
        # in the documented vocabulary (``suffix: (none)`` /
        # ``config: absent``); the actionable hint lives on stderr so
        # automation can keep grepping stdout for state.
        from pathlib import Path

        from vrcpilot.mic import linux as mic_linux

        config_dir = "/tmp/vrcpilot-fake-pipewire-empty.d"

        def fake_config_path(*, suffix: str = "") -> Path:
            name = "vrcpilot-mic.conf" if not suffix else f"vrcpilot-mic-{suffix}.conf"
            return Path(config_dir) / name

        monkeypatch.setattr(mic_linux, "config_path", fake_config_path)
        monkeypatch.setattr(mic_linux, "iter_registered_suffixes", list)

        rc = main(["linux-mic", "status", "--all"])

        captured = capsys.readouterr()
        assert rc == 0
        stdout_lines = captured.out.splitlines()
        assert stdout_lines[0] == "suffix: (none)"
        assert stdout_lines[1] == "config: absent"
        assert stdout_lines[2] == f"config_path: {config_dir}/"
        assert (
            "No vrcpilot-mic config fragments found. "
            "Run 'vrcpilot linux-mic register' first." in captured.err
        )


class TestLinuxMicRegisterSuffixed:
    """``register`` honors ``--suffix`` and surfaces VRChat-side guidance.

    The VRChat-side hint must name the *exact* description the user has
    to pick from VRChat's Audio dropdown (``Monitor of <description>``);
    if the suffix is non-empty, ``<description>`` carries the suffix
    too. Invalid suffixes turn into a structured ``vrcpilot: invalid
    suffix:`` line with exit code 2 -- distinct from a generic crash
    so callers can ``$?`` discriminate.
    """

    def test_register_default_message_mentions_virtual_mic(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # Default path: the hint references the unsuffixed
        # ``VRCPilot_Virtual_Mic`` description; the user copy-pastes
        # this string into VRChat Audio settings.
        from pathlib import Path

        from vrcpilot.mic import linux as mic_linux
        from vrcpilot.mic.linux import RegisterResult

        def fake_register(*, suffix: str = "", runtime_load: bool = True):
            return RegisterResult(
                config_path=Path("/tmp/vrcpilot-mic.conf"),
                created_config=True,
                runtime_loaded=True,
                runtime_warning=None,
                suffix=suffix,
            )

        monkeypatch.setattr(mic_linux, "register_virtual_mic", fake_register)

        rc = main(["linux-mic", "register", "--no-runtime-load"])

        assert rc == 0
        assert "Monitor of VRCPilot_Virtual_Mic" in capsys.readouterr().err

    def test_register_with_suffix_message_mentions_suffixed_description(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # Non-empty suffix path: the description is suffixed
        # (``VRCPilot_Virtual_Mic_alt``) so two coexisting registrations
        # show up as distinct entries in VRChat's audio picker.
        from pathlib import Path

        from vrcpilot.mic import linux as mic_linux
        from vrcpilot.mic.linux import RegisterResult

        def fake_register(*, suffix: str = "", runtime_load: bool = True):
            return RegisterResult(
                config_path=Path(f"/tmp/vrcpilot-mic-{suffix}.conf"),
                created_config=True,
                runtime_loaded=True,
                runtime_warning=None,
                suffix=suffix,
            )

        monkeypatch.setattr(mic_linux, "register_virtual_mic", fake_register)

        rc = main(["linux-mic", "register", "--suffix", "alt"])

        assert rc == 0
        assert "Monitor of VRCPilot_Virtual_Mic_alt" in capsys.readouterr().err

    def test_register_invalid_suffix_exits_with_code_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # ``register_virtual_mic`` raises ``ValueError`` for any
        # suffix the underlying validator rejects; the CLI must
        # convert that into a structured ``invalid suffix:`` line on
        # stderr and exit 2 so scripts can distinguish input errors
        # from unexpected crashes.
        from vrcpilot.mic import linux as mic_linux

        def fake_register(*, suffix: str = "", runtime_load: bool = True):
            raise ValueError(f"bad suffix {suffix!r}")

        monkeypatch.setattr(mic_linux, "register_virtual_mic", fake_register)

        rc = main(["linux-mic", "register", "--suffix", "!!bad"])

        assert rc == 2
        err = capsys.readouterr().err
        assert "vrcpilot: invalid suffix:" in err


class TestLinuxMicUnregisterSuffixed:
    """``unregister --all`` iteration and empty-state messaging.

    ``--all`` is a sweep operation: it pulls the suffix list from
    ``iter_registered_suffixes`` and unregisters each one. Empty input
    is success (nothing to do, exit 0) rather than an error; populated
    input fans out to one ``unregister_virtual_mic(suffix=...)`` call
    per entry in iteration order.
    """

    def test_unregister_all_with_no_registrations_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # Empty registration set -> exit 0 with an informational line
        # on stderr. Exiting non-zero here would make idempotent
        # cleanup scripts (``unregister --all`` after a fresh boot)
        # spuriously fail.
        from vrcpilot.mic import linux as mic_linux

        monkeypatch.setattr(mic_linux, "iter_registered_suffixes", list)

        # Guard rail: even if the implementation accidentally falls
        # through, we want to know it tried to talk to pulsectl by
        # raising loudly rather than silently succeeding.
        def must_not_call(**_: object) -> bool:
            raise AssertionError(
                "unregister_virtual_mic must not be called when the "
                "registration set is empty"
            )

        monkeypatch.setattr(mic_linux, "unregister_virtual_mic", must_not_call)

        rc = main(["linux-mic", "unregister", "--all"])

        assert rc == 0
        assert "No VRCPilotMic registrations to remove" in capsys.readouterr().err

    def test_unregister_all_iterates_through_suffixes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # The order in ``iter_registered_suffixes`` is the order the
        # CLI must unregister in. We record each call's ``suffix``
        # kwarg and assert both the count and the sequence.
        from vrcpilot.mic import linux as mic_linux

        monkeypatch.setattr(mic_linux, "iter_registered_suffixes", lambda: ["", "alt"])

        observed_suffixes: list[str] = []

        def fake_unregister(*, suffix: str = "") -> bool:
            observed_suffixes.append(suffix)
            return True

        monkeypatch.setattr(mic_linux, "unregister_virtual_mic", fake_unregister)

        rc = main(["linux-mic", "unregister", "--all"])

        assert rc == 0
        assert observed_suffixes == ["", "alt"]


class TestLinuxMicStatus:
    """``status`` returns 0 even when probes fail; stdout stays parseable.

    The contract is split-stream: stdout carries the answer with a fixed
    vocabulary (``present`` / ``absent`` / ``loaded`` / ``not loaded`` /
    ``unavailable`` / ``visible`` / ``not visible``), and any probe-side
    error lands on stderr as ``<channel>: error: <message>``.
    """

    def test_returns_zero(self, capsys: pytest.CaptureFixture[str]):
        # No PipeWire daemon on the test runner is fine -- status is
        # designed to surface ``unavailable`` rather than raise.
        assert main(["linux-mic", "status"]) == 0
        # Some stdout output is guaranteed (config / runtime / soundcard
        # lines); the precise content depends on host state.
        assert capsys.readouterr().out != ""

    def test_stdout_includes_config_line(self, capsys: pytest.CaptureFixture[str]):
        main(["linux-mic", "status"])
        stdout = capsys.readouterr().out
        # The "config: present|absent" prefix is part of the stable
        # vocabulary downstream scripts grep for.
        assert "config:" in stdout

    def test_stdout_includes_config_path(self, capsys: pytest.CaptureFixture[str]):
        main(["linux-mic", "status"])
        stdout = capsys.readouterr().out
        assert "config_path:" in stdout
