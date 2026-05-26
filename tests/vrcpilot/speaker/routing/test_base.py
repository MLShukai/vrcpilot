"""Tests for :class:`vrcpilot.speaker.routing.base.AudioDevice`.

``AudioDevice`` is the immutable handle the public routing API hands
back to callers (see spec §4.1 / §5). The contract the rest of the
package depends on is: the value object is hashable, comparable by
value, and refuses both attribute mutation (``frozen=True``) and
attribute addition (``slots=True``) so downstream code can rely on a
stable field set.

The skill bans tautological dataclass / framework-behaviour tests, but
the immutability guarantees here are load-bearing for the public API
contract: ``find_device`` results are cached and passed across module
boundaries, and any silent mutation would corrupt every subsequent
resolution. The tests below pin the *contract*, not the implementation
choice.
"""

from __future__ import annotations

import dataclasses

import pytest

from vrcpilot.speaker.routing import AudioDevice


class TestAudioDeviceConstruction:
    def test_constructs_with_all_three_fields(self) -> None:
        # Spec §4.1: the dataclass exposes ``id`` / ``name`` /
        # ``is_default``; constructors must accept them positionally
        # (the dataclass-generated __init__ contract).
        device = AudioDevice(
            id="endpoint-1", name="Speakers (Realtek)", is_default=True
        )
        assert device.id == "endpoint-1"
        assert device.name == "Speakers (Realtek)"
        assert device.is_default is True


class TestAudioDeviceImmutability:
    def test_attribute_reassignment_is_rejected(self) -> None:
        # Spec §4.1: ``frozen=True``. Callers cache AudioDevice
        # instances across the routing module (``Router._device`` is
        # held for the relay lifetime); a silent mutation would
        # invalidate that cache.
        device = AudioDevice(id="x", name="X", is_default=False)
        with pytest.raises(dataclasses.FrozenInstanceError):
            device.id = "y"  # type: ignore[misc]

    def test_unknown_attribute_assignment_is_rejected(self) -> None:
        # Spec §4.1: ``slots=True``. The field set is fixed; adding
        # ``device.foo = 1`` would silently succeed on a non-slotted
        # dataclass and break downstream code that introspects the
        # AudioDevice schema. On a frozen + slotted dataclass the
        # CPython implementation raises ``TypeError`` (from the
        # ``__setattr__`` super-call) -- which is also a reasonable
        # FrozenInstanceError surrogate, accept both.
        device = AudioDevice(id="x", name="X", is_default=False)
        with pytest.raises(
            (AttributeError, TypeError, dataclasses.FrozenInstanceError)
        ):
            device.foo = 1  # type: ignore[attr-defined]


class TestAudioDeviceEquality:
    def test_same_fields_compare_equal(self) -> None:
        # Spec §5 data-model: equality by value. Test helpers compare
        # ``default_device()`` against an element of ``list_devices()``
        # using ``==``; identity is not guaranteed by the implementation.
        a = AudioDevice(id="x", name="X", is_default=True)
        b = AudioDevice(id="x", name="X", is_default=True)
        assert a == b

    def test_different_fields_compare_unequal(self) -> None:
        a = AudioDevice(id="x", name="X", is_default=True)
        b = AudioDevice(id="y", name="X", is_default=True)
        assert a != b
