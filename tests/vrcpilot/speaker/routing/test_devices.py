"""Integration-real tests for ``vrcpilot.speaker.routing.devices``.

Per spec §6.1 (decision: case B) and §6.3 the device-enumeration layer
exercises the **real** :mod:`soundcard` package against whatever audio
backend the host exposes (PipeWire on Linux, WASAPI on Windows). The
skill bans :class:`FakeSoundCard*` mocks; instead this file is
module-level skipped when soundcard cannot import or finds zero output
devices, leaving the assertions to run on a real machine.

A few tests are conditionally skipped when the host happens to expose
only a single output device -- the ambiguity / 0-device branches of
``find_device`` cannot be observed in that case. Those branches are
still pinned by ``test_router.py`` and the CLI tests through error
substring checks, so the coverage gap is bounded.
"""

from __future__ import annotations

import sys

import pytest

# soundcard imports libpulse / WASAPI eagerly; on a host without either
# (notably Windows CI runners with no audio service, or a CI Linux
# runner without PipeWire) ``import soundcard`` raises. Collect the
# skip at module level so one missing-resource branch fires per file.
sys.argv = sys.argv or ["pytest"]  # soundcard reads sys.argv[1]
try:
    import soundcard as _sc  # type: ignore[import-not-found]
except Exception as _exc:  # noqa: BLE001 -- any load failure -> skip
    pytest.skip(
        f"soundcard is unavailable on this host: {_exc}",
        allow_module_level=True,
    )

# Touch _sc so ruff does not flag the import as unused even when no
# test below references it directly.
_ = _sc


from vrcpilot.speaker.routing import (  # noqa: E402
    AudioDevice,
    AudioRoutingError,
    DeviceNotFoundError,
    default_device,
    find_device,
    list_devices,
)


@pytest.fixture(scope="module")
def devices() -> list[AudioDevice]:
    """List output devices once per module to avoid repeated dlopen costs."""
    return list_devices()


pytestmark = pytest.mark.integration_real


class TestListDevices:
    def test_returns_non_empty_when_host_has_outputs(
        self, devices: list[AudioDevice]
    ) -> None:
        # Spec F1.1: enumerate every available output speaker. Hosts
        # without any output device skip the rest of this module
        # via the conftest-level guard below.
        if not devices:
            pytest.skip("no output devices on this host; nothing to enumerate")
        assert len(devices) >= 1

    def test_default_device_appears_first_when_present(
        self, devices: list[AudioDevice]
    ) -> None:
        # Spec F1.2: default (if any) is first, then name ascending.
        if not devices:
            pytest.skip("no output devices on this host")
        defaults = [d for d in devices if d.is_default]
        # F1.3: 0 or 1 default at most.
        assert len(defaults) <= 1
        if defaults:
            assert devices[0].is_default is True

    def test_tail_is_sorted_by_name_ascending(self, devices: list[AudioDevice]) -> None:
        # Spec F1.2 (b): post-default ordering is Python's default
        # string comparison (Unicode codepoint, case-sensitive).
        if len(devices) < 3:
            pytest.skip("need >=3 devices to observe sort ordering of the tail")
        # The default (if any) is at index 0; the remainder must be
        # monotonically non-decreasing by name.
        tail_start = 1 if devices[0].is_default else 0
        tail_names = [d.name for d in devices[tail_start:]]
        assert tail_names == sorted(tail_names)


class TestDefaultDevice:
    def test_default_device_matches_list_devices_head(
        self, devices: list[AudioDevice]
    ) -> None:
        # Spec F1.5 + F1.2 (a): ``default_device()`` and
        # ``list_devices()[0]`` must agree when any output exists.
        if not devices:
            pytest.skip("no output devices on this host")
        assert default_device() == devices[0]

    def test_default_device_is_marked_is_default(self) -> None:
        # Spec §4.1 invariant: a device returned by ``default_device``
        # carries ``is_default == True``.
        try:
            device = default_device()
        except DeviceNotFoundError:
            pytest.skip("no output devices on this host")
        assert device.is_default is True


class TestFindDeviceIdExact:
    def test_exact_id_match_returns_same_device(
        self, devices: list[AudioDevice]
    ) -> None:
        # Spec F1.6 step 1: an exact ``device.id`` match resolves
        # immediately and bypasses name resolution.
        if not devices:
            pytest.skip("no output devices on this host")
        target = devices[0]
        assert find_device(target.id) == target


class TestFindDeviceNameExact:
    def test_exact_name_match_returns_same_device(
        self, devices: list[AudioDevice]
    ) -> None:
        # Spec F1.6 step 2: exact ``device.name`` (case-sensitive)
        # match resolves when the id step found nothing.
        if not devices:
            pytest.skip("no output devices on this host")
        # Pick a device whose name is unique so step 2 resolves cleanly.
        names = [d.name for d in devices]
        unique = next(
            (d for d in devices if names.count(d.name) == 1),
            None,
        )
        if unique is None:
            pytest.skip("no uniquely-named device to exercise exact-name path")
        assert find_device(unique.name) == unique


class TestFindDeviceNameSubstring:
    def test_substring_match_resolves_when_single_hit(
        self, devices: list[AudioDevice]
    ) -> None:
        # Spec F1.6 step 3: case-insensitive substring of ``name``.
        # Need a device whose name has a non-empty unique prefix; if
        # none exists, skip rather than fabricate.
        if not devices:
            pytest.skip("no output devices on this host")
        unique_substring: tuple[AudioDevice, str] | None = None
        for d in devices:
            if not d.name:
                continue
            # Try progressively shorter substrings.
            for length in range(min(len(d.name), 8), 1, -1):
                needle = d.name[:length].lower()
                if not needle:
                    continue
                hits = [other for other in devices if needle in other.name.lower()]
                if len(hits) == 1:
                    unique_substring = (d, needle)
                    break
            if unique_substring is not None:
                break
        if unique_substring is None:
            pytest.skip("no device name yields a unique substring on this host")
        target, needle = unique_substring
        assert find_device(needle) == target


class TestFindDeviceZeroHit:
    def test_zero_hit_raises_with_listing(self, devices: list[AudioDevice]) -> None:
        # Spec F1.8 + §9.2: zero hits -> DeviceNotFoundError whose
        # message contains the query and a listing of the available
        # devices (names / ids).
        if not devices:
            pytest.skip("no output devices on this host")
        bogus = "definitely-not-a-real-device-zzz-vrcpilot-routing-test"
        with pytest.raises(DeviceNotFoundError) as excinfo:
            find_device(bogus)
        msg = str(excinfo.value)
        assert bogus in msg
        # F1.8 / §9.2 requires the listing; sample-check by asserting
        # at least one real device name shows up in the message.
        assert any(d.name in msg for d in devices)


class TestFindDeviceAmbiguous:
    def test_ambiguous_substring_raises_audio_routing_error(
        self, devices: list[AudioDevice]
    ) -> None:
        # Spec F1.7 + §9.2: a substring matching >=2 device names
        # raises ``AudioRoutingError`` (NOT DeviceNotFoundError) and
        # the message enumerates the conflicting devices.
        if len(devices) < 2:
            pytest.skip("need >=2 devices to exercise the ambiguity branch")
        # Look for any substring that hits >=2 names.
        ambiguous_needle: str | None = None
        for d in devices:
            for length in range(1, min(len(d.name), 8) + 1):
                needle = d.name[:length].lower()
                if not needle:
                    continue
                hits = sum(1 for other in devices if needle in other.name.lower())
                if hits >= 2:
                    ambiguous_needle = needle
                    break
            if ambiguous_needle is not None:
                break
        if ambiguous_needle is None:
            pytest.skip("no substring matches multiple names on this host")
        with pytest.raises(AudioRoutingError) as excinfo:
            find_device(ambiguous_needle)
        # Per the ``DeviceNotFoundError(AudioRoutingError)`` hierarchy,
        # the ambiguity branch must NOT be the "not found" subtype --
        # F1.7 explicitly distinguishes them.
        assert not isinstance(excinfo.value, DeviceNotFoundError)
        msg = str(excinfo.value)
        assert ambiguous_needle in msg.lower() or ambiguous_needle in msg
