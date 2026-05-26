"""Contract-pin tests for the routing exception hierarchy.

The skill normally bans ``issubclass`` / inheritance tests as
tautological; the public API contract pin exception (skill §"公開 API
契約ピン") applies here because:

* External callers write ``except vrcpilot.speaker.routing.AudioRoutingError``
  expecting to catch ``DeviceNotFoundError`` too. The hierarchy is
  load-bearing for that idiom and Hyrum's-law-fragile.
* ``AudioRoutingError`` inherits from ``RuntimeError`` per spec §4.1 /
  §F4.1 so callers who do not want to import the routing module can
  still net these failures with a ``RuntimeError`` catch (the CLI
  generic-error branch does exactly this).

These are pins, not behaviour tests -- they exist to make a silent
re-parenting of the exception classes loud during code review.
"""

from __future__ import annotations

import pytest

from vrcpilot.speaker.routing import AudioRoutingError, DeviceNotFoundError


@pytest.mark.api_contract
class TestRoutingExceptionHierarchy:
    def test_audio_routing_error_is_runtime_error(self) -> None:
        # Spec §F4.1: ``AudioRoutingError`` MUST subclass RuntimeError
        # so the CLI's generic ``except RuntimeError`` branch catches
        # routing-specific failures uniformly.
        assert issubclass(AudioRoutingError, RuntimeError)

    def test_device_not_found_is_audio_routing_error(self) -> None:
        # Spec §F4.2: callers should be able to catch the broad
        # ``AudioRoutingError`` and net the narrower
        # ``DeviceNotFoundError`` too.
        assert issubclass(DeviceNotFoundError, AudioRoutingError)


@pytest.mark.api_contract
class TestRoutingExceptionMessage:
    def test_audio_routing_error_str_preserves_constructor_argument(self) -> None:
        # Spec §9.2 substring-based message checks: tests assert
        # message fragments via ``in str(exc)``. This requires the
        # constructor argument to round-trip through ``str(exc)``,
        # which the RuntimeError base class provides -- pinned here
        # because regressing this would break every other error-message
        # test in this package.
        err = AudioRoutingError("multiple matches for 'Speakers'")
        assert "multiple matches for 'Speakers'" in str(err)

    def test_device_not_found_error_str_preserves_constructor_argument(self) -> None:
        err = DeviceNotFoundError("no output device matches 'xyzzy'")
        assert "no output device matches 'xyzzy'" in str(err)
