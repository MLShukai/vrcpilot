"""Tests for :mod:`vrcpilot.cli.screenshot`.

``vrcpilot screenshot`` orchestrates :func:`vrcpilot.screenshot.take_screenshot`
plus :meth:`vrcpilot.screenshot.Screenshot.save`. The actual capture
requires a running VRChat plus a graphical session (Win32 mss / X11),
so the only contract we can lock in here without e2e infrastructure is
the failure-path behaviour:

* When VRChat is not running (autouse default) ``take_screenshot``
  returns ``None`` and the CLI exits 1 with a single
  ``vrcpilot: could not capture VRChat screenshot`` stderr line.

The YAML payload structure (``path:`` vs inline base64 ``image:``) is
already covered by :class:`vrcpilot.screenshot.Screenshot.save` tests
in the screenshot module. The CLI just calls ``shot.save(output)`` and
writes the returned text -- there is no additional CLI behaviour to
exercise beyond the failure path and argparse plumbing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vrcpilot.cli import build_parser, main


class TestScreenshotNoVRChat:
    """Without a VRChat process running, ``screenshot`` exits 1."""

    def test_exits_with_code_one(self, tmp_path: Path):
        # ``take_screenshot`` calls ``focus()`` which fails (no PID),
        # returns ``None``, and the CLI maps that to exit 1.
        assert main(["screenshot", "-o", str(tmp_path / "out.png")]) == 1

    def test_stderr_has_diagnostic_message(
        self,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ):
        main(["screenshot", "-o", str(tmp_path / "out.png")])
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "vrcpilot: could not capture VRChat screenshot" in captured.err

    def test_no_png_written_on_failure(self, tmp_path: Path):
        target = tmp_path / "should-not-exist.png"
        main(["screenshot", "-o", str(target)])
        assert not target.exists()


class TestScreenshotArgparse:
    """Argparse plumbing on the ``screenshot`` subparser."""

    def test_output_flag_long_form(self, tmp_path: Path):
        target = tmp_path / "out.png"
        ns = build_parser().parse_args(["screenshot", "--output", str(target)])
        assert ns.output == target

    def test_output_flag_short_form(self, tmp_path: Path):
        target = tmp_path / "out.png"
        ns = build_parser().parse_args(["screenshot", "-o", str(target)])
        assert ns.output == target

    def test_output_defaults_to_none(self):
        ns = build_parser().parse_args(["screenshot"])
        assert ns.output is None

    def test_pid_flag_accepts_int(self):
        ns = build_parser().parse_args(["screenshot", "--pid", "9876"])
        assert ns.pid == 9876

    def test_pid_defaults_to_none(self):
        ns = build_parser().parse_args(["screenshot"])
        assert ns.pid is None
