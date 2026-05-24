"""Windows-side dispatch test for :func:`_select_speaker_backend`.

Mirror of ``test_session_linux.py`` for Windows. ``vrcpilot.speaker.windows``
raises ``ImportError`` on non-Windows hosts (the proc-tap dependency is
gated to ``sys_platform == 'win32'``), so the module-level skip below
prevents pytest collection from crashing on Linux CI.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only dispatch test", allow_module_level=True)

from pytest_mock import MockerFixture  # noqa: E402

from vrcpilot.speaker.session import _select_speaker_backend  # noqa: E402


class TestWindowsDispatch:
    def test_select_returns_proctap_backend_with_forwarded_kwargs(
        self, mocker: MockerFixture
    ) -> None:
        # Symmetric with the Linux variant: the dispatch lazy-imports
        # ProcTapSpeakerBackend on Windows runners. Patching the bound
        # name on the windows module keeps the test from needing a
        # real proc-tap session.
        from vrcpilot.speaker import windows as speaker_windows

        sentinel = object()
        spy = mocker.patch.object(
            speaker_windows, "ProcTapSpeakerBackend", return_value=sentinel
        )

        result = _select_speaker_backend(read_timeout=2.5, pid=4242)

        assert result is sentinel
        spy.assert_called_once_with(read_timeout=2.5, pid=4242)
