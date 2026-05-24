"""Linux-specific tests for :mod:`vrcpilot.mic.devices`.

Exercises the **real** ``default_device_name`` constant on Linux plus
``lookup_speaker`` driving real :mod:`soundcard` against the live
PulseAudio / PipeWire daemon. A Windows-side counterpart belongs in a
sibling ``test_devices_windows.py`` whenever a Windows runner is
available -- we deliberately do not patch ``sys.platform`` to fake the
other host.
"""

from __future__ import annotations

import sys

import pytest

if not sys.platform.startswith("linux"):
    pytest.skip("Linux-only mic-devices tests", allow_module_level=True)

# soundcard is a lazy import inside ``lookup_speaker``; calling it at
# module level forces the libpulse dlopen to surface here (so the skip
# fires once for the whole file rather than per-test).
sys.argv = sys.argv or ["pytest"]  # noqa: E402  -- soundcard reads sys.argv[1]
try:
    import soundcard as _sc  # type: ignore[import-not-found]  # noqa: E402
except Exception as _exc:  # noqa: BLE001 -- libpulse load failures all collapse to skip
    pytest.skip(
        f"soundcard is unavailable on this Linux host: {_exc}",
        allow_module_level=True,
    )


from vrcpilot.mic.base import VIRTUAL_MIC_SINK_NAME  # noqa: E402
from vrcpilot.mic.devices import default_device_name, lookup_speaker  # noqa: E402


class TestLinuxDefault:
    def test_default_is_vrcpilot_mic_sink_name(self) -> None:
        # The mic.linux register flow installs a sink named
        # ``VIRTUAL_MIC_SINK_NAME``; the default device lookup must
        # resolve to the same string so a freshly-registered host
        # works without ``--device`` / ``$VRCPILOT_MIC_DEVICE``.
        assert default_device_name() == VIRTUAL_MIC_SINK_NAME


class TestLookupSpeakerAgainstRealSoundcard:
    def test_returns_a_speaker_when_match_exists(self) -> None:
        # Use whichever speaker the OS currently exposes; we cannot
        # presume any specific device, only that lookup_speaker returns
        # one of the speakers ``soundcard`` enumerates when the query
        # is a substring of an existing name.
        all_speakers = list(_sc.all_speakers())
        if not all_speakers:
            pytest.skip("no output devices on this host; nothing to look up")
        target = all_speakers[0]
        # Use the first 4 characters of the name as a permissive
        # substring (case-insensitive substring match is documented).
        needle = target.name[:4]
        if not needle:
            pytest.skip("first speaker has empty name; cannot construct needle")
        speaker = lookup_speaker(needle)
        # The contract is "some matching speaker", not identity --
        # multiple devices may legitimately match the substring.
        assert (
            needle.lower() in str(speaker.name).lower()
            or needle.lower() in str(speaker.id).lower()
        )

    def test_raises_with_listing_when_no_match(self) -> None:
        # A clearly-bogus needle must raise MicDeviceNotFoundError; the
        # error message must enumerate the visible devices so the user
        # can pick from what is actually available, and it must surface
        # the Linux-specific install hint (vrcpilot linux-mic register)
        # rather than the Windows hint.
        from vrcpilot.mic.base import MicDeviceNotFoundError

        with pytest.raises(MicDeviceNotFoundError) as excinfo:
            lookup_speaker("definitely-not-a-real-device-zzz-vrcpilot-test-marker")
        msg = str(excinfo.value)
        assert "definitely-not-a-real-device" in msg
        # Linux-specific install hint.
        assert "vrcpilot linux-mic register" in msg
        # Windows-specific hint must NOT leak onto Linux.
        assert "vb-audio.com" not in msg.lower()
