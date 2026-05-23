"""Tests for :mod:`vrcpilot.controls.errors`.

Both errors must remain ``RuntimeError`` subclasses so existing
``except RuntimeError`` blocks (e.g. broad CLI handlers) keep
working when controls APIs are introduced.
"""

from __future__ import annotations

import pytest

from vrcpilot.controls.errors import VRChatNotFocusedError
from vrcpilot.process import VRChatNotRunningError


@pytest.mark.parametrize(
    "exc_cls",
    [VRChatNotRunningError, VRChatNotFocusedError],
)
class TestErrorHierarchy:
    def test_inherits_runtime_error(self, exc_cls: type[RuntimeError]):
        assert issubclass(exc_cls, RuntimeError)

    def test_can_be_raised_and_caught_as_runtime_error(
        self, exc_cls: type[RuntimeError]
    ):
        with pytest.raises(RuntimeError):
            raise exc_cls("boom")

    def test_message_round_trips(self, exc_cls: type[RuntimeError]):
        with pytest.raises(exc_cls) as info:
            raise exc_cls("custom message")
        assert "custom message" in str(info.value)
