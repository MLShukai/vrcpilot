"""Tests for :mod:`vrcpilot.mic.devices` resolution logic.

Only platform-agnostic resolution rules live here; per-platform default
device strings are tested in the platform-split files (``test_devices_linux.py``
on Linux; the Windows counterpart will be added if a Windows runner ever
needs it). ``lookup_speaker`` exercises a real :mod:`soundcard` import
and so lives in :mod:`tests.vrcpilot.mic.test_devices_linux` /
``...test_devices_windows`` where the runtime libpulse / WASAPI is
actually present.

Why no ``sys.platform`` monkeypatching: it gives a false sense of
cross-platform coverage. The default-device lookup is a 1-line
dictionary read; the real coverage we care about is that the platform
constant exists and a real :mod:`soundcard` query succeeds against it.
"""

from __future__ import annotations

import pytest

from vrcpilot.mic.base import DEVICE_ENV_VAR, MicDeviceNotFoundError
from vrcpilot.mic.devices import default_device_name, resolve_device_name


class TestResolveDeviceName:
    """``resolve_device_name`` priority: argument > env > OS default."""

    def test_argument_wins_over_env_and_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEVICE_ENV_VAR, "from-env")
        assert resolve_device_name("from-arg") == "from-arg"

    def test_env_used_when_argument_omitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEVICE_ENV_VAR, "envname")
        assert resolve_device_name(None) == "envname"

    def test_empty_env_falls_through_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Empty string in the env var is treated like "unset"; otherwise
        # users who export the variable to clear it (a common shell
        # convention) would silently disable the OS default.
        monkeypatch.setenv(DEVICE_ENV_VAR, "")
        default = default_device_name()
        if default is None:
            with pytest.raises(MicDeviceNotFoundError):
                resolve_device_name(None)
        else:
            assert resolve_device_name(None) == default

    def test_default_used_when_both_argument_and_env_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DEVICE_ENV_VAR, raising=False)
        default = default_device_name()
        if default is None:
            # On a platform without a default, expect the documented
            # raise; the error must name the env-var so users know how
            # to recover.
            with pytest.raises(MicDeviceNotFoundError) as excinfo:
                resolve_device_name(None)
            assert DEVICE_ENV_VAR in str(excinfo.value)
        else:
            assert resolve_device_name(None) == default
