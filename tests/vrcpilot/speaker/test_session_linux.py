"""Linux-side dispatch test for :func:`_select_speaker_backend`.

Verifies that on a Linux runner the session module's lazy import
resolves to :class:`PipeWireSpeakerBackend` and forwards kwargs
verbatim. The Windows symmetric test lives in
``test_session_windows.py`` (module-level skipped on non-Windows hosts).

Why not ``sys.platform`` monkeypatching: the skill bans it as
"false cross-platform coverage" -- the real bug we care about is
"on Linux the import path resolves to the Linux backend", which can
only be observed *on Linux*.
"""

from __future__ import annotations

import sys

import pytest

if not sys.platform.startswith("linux"):
    pytest.skip("Linux-only dispatch test", allow_module_level=True)

from pytest_mock import MockerFixture  # noqa: E402

from vrcpilot.speaker.session import _select_speaker_backend  # noqa: E402


class TestLinuxDispatch:
    def test_select_returns_pipewire_backend_with_forwarded_kwargs(
        self, mocker: MockerFixture
    ) -> None:
        # The dispatch is lazy: ``from vrcpilot.speaker.linux import
        # PipeWireSpeakerBackend`` runs inside ``_select_speaker_backend``
        # so we patch on that module's binding. ``return_value`` keeps
        # the test from needing a real PipeWire daemon to construct
        # the backend.
        from vrcpilot.speaker import linux as speaker_linux

        sentinel = object()
        spy = mocker.patch.object(
            speaker_linux, "PipeWireSpeakerBackend", return_value=sentinel
        )

        result = _select_speaker_backend(read_timeout=2.5, pid=4242)

        assert result is sentinel
        spy.assert_called_once_with(read_timeout=2.5, pid=4242)
