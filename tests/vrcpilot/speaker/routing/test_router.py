"""Tests for :class:`vrcpilot.speaker.routing.Router` and ``route``.

Q1 (spec §12) decision: T-R8 / T-R9 (empty-frame skip vs non-empty
frame transfer) are covered through the **integration_real** seam --
real soundcard player driven by FakeSpeakerLoop emitting a mix of
empty and non-empty frames -- rather than by poking ``Router._on_frames``
directly. The skill bans testing internal implementation details, and
the alternative (mocking the player) is explicitly forbidden under the
"no 3rd-party surface mocks" rule. The downside is that automated
tests can only observe "no crash / underrun" rather than asserting
"play() was not called for empties" -- the precise behavioural pin is
deferred to the Phase 6 manual e2e per spec §6.4.

Q5 decision: ``FakeSpeakerLoop`` is extended (in ``tests/fakes/audio.py``)
with ``start_side_effect`` / ``stop_side_effect`` / ``is_running`` /
``stop`` / ``close`` so the Router's start-rollback (T-R12),
stop-exception-propagation (T-R11), and double-stop (T-R6) behaviours
can all be exercised against the same single seam. These knobs mirror
the production :class:`SpeakerLoop` surface 1:1 -- they are NOT a
3rd-party mock.

The integration-with-fakes section patches the ``SpeakerLoop`` binding
inside ``vrcpilot.speaker.routing.router`` (the module the Router
imports through). That is the project's standard "swap a vrcpilot-owned
ABC at its consumption site" pattern and is allowed by the skill.

Note on soundcard dependency: ``Router.start()`` opens a real
``soundcard`` player even when the speaker loop is faked (spec §6.4
"integration-with-fakes (FakeSpeakerLoop を使う、ただし soundcard
player は実機を開く)"). Tests that exercise ``start()`` therefore
require a real default output device and live under the
``integration_real`` marker. Construction-only tests (no ``start()``)
remain pure integration-with-fakes and run on every host.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest
from pytest_mock import MockerFixture

from tests.fakes import FakeSpeakerLoop
from vrcpilot.speaker.routing import (
    AudioDevice,
    Router,
    route,
)


@pytest.fixture(autouse=True)
def _reset_fake_speaker_loop() -> Iterator[None]:
    """Reset every class-level knob on :class:`FakeSpeakerLoop`.

    Knobs leaking between tests would mask real bugs (a test that
    leaves ``start_side_effect`` set would force the next test's
    ``start()`` to raise unexpectedly). Reset on entry AND exit so a
    router-side test cannot pollute downstream record-side tests that
    reuse the same fake.
    """
    FakeSpeakerLoop.instances = []
    FakeSpeakerLoop.frames_per_start = 3
    FakeSpeakerLoop.samples_per_frame = 1024
    FakeSpeakerLoop.init_side_effect = None
    FakeSpeakerLoop.start_side_effect = None
    FakeSpeakerLoop.stop_side_effect = None
    yield
    FakeSpeakerLoop.instances = []
    FakeSpeakerLoop.frames_per_start = 3
    FakeSpeakerLoop.samples_per_frame = 1024
    FakeSpeakerLoop.init_side_effect = None
    FakeSpeakerLoop.start_side_effect = None
    FakeSpeakerLoop.stop_side_effect = None


def _patch_speaker_loop(mocker: MockerFixture) -> type[FakeSpeakerLoop]:
    """Substitute the ``SpeakerLoop`` factory inside the router module.

    The router consumes ``from vrcpilot.speaker import SpeakerLoop`` (or
    equivalent re-export) at module import time. Patching the binding
    at the consumption site is the canonical pattern used by
    ``test_loop.py`` and ``test_command.py``.
    """
    mocker.patch("vrcpilot.speaker.routing.router.SpeakerLoop", FakeSpeakerLoop)
    return FakeSpeakerLoop


def _synthetic_device() -> AudioDevice:
    """Synthetic AudioDevice used only by construction-time tests.

    Tests that never call ``Router.start()`` can pass this without
    opening any soundcard backend. As soon as ``start()`` is called the
    Router will call ``soundcard.get_speaker(id)`` and reject this
    synthetic id, so any test that needs to start the router must use
    the ``real_default_device`` fixture instead.
    """
    return AudioDevice(id="fake-id", name="Fake Device", is_default=False)


# soundcard imports libpulse / WASAPI eagerly; on a host without either
# the start()-driven tests below cannot run. A function-level skip via
# the ``real_default_device`` fixture lets the rest of this module
# (construction-only tests) keep running on every platform.
try:
    sys.argv = sys.argv or ["pytest"]
    import soundcard as _sc  # type: ignore[import-not-found]  # noqa: F401

    _SOUNDCARD_AVAILABLE = True
except Exception:  # noqa: BLE001 -- any load failure -> skip int_real tests
    _SOUNDCARD_AVAILABLE = False


@pytest.fixture
def real_default_device() -> AudioDevice:
    """Resolve the OS default speaker via the real ``soundcard`` package.

    Any test depending on this fixture is implicitly integration_real:
    it requires a working audio backend. Skips cleanly on hosts where
    soundcard cannot load or no default exists.
    """
    if not _SOUNDCARD_AVAILABLE:
        pytest.skip("soundcard unavailable on this host")
    from vrcpilot.speaker.routing import default_device

    try:
        return default_device()
    except Exception as exc:  # noqa: BLE001 -- any default lookup failure -> skip
        pytest.skip(f"no default output device available: {exc}")


# ---------------------------------------------------------------------------
# Construction-only tests: no soundcard backend needed
# ---------------------------------------------------------------------------


class TestRouterConstruction:
    def test_is_running_false_before_start(self, mocker: MockerFixture) -> None:
        # Spec F2.1: constructor MUST NOT open capture / output streams.
        # ``is_running`` therefore reports False until ``start()``.
        _patch_speaker_loop(mocker)
        router = Router(pid=12345, device=_synthetic_device())
        assert router.is_running is False
        # No SpeakerLoop should have been built either.
        assert FakeSpeakerLoop.instances == []

    def test_device_property_returns_resolved_audio_device(
        self, mocker: MockerFixture
    ) -> None:
        # Spec F2.9: ``device`` property returns the AudioDevice that
        # __init__ resolved, both before and after start.
        _patch_speaker_loop(mocker)
        device = _synthetic_device()
        router = Router(pid=12345, device=device)
        assert router.device == device


# ---------------------------------------------------------------------------
# integration_real: FakeSpeakerLoop + real soundcard player
#
# All Router lifecycle tests below need a real soundcard player because
# Router.start() resolves the AudioDevice.id against soundcard's
# enumeration before opening the output stream. Per spec §6.4 this
# combination ("FakeSpeakerLoop but real player") is the documented
# integration-with-fakes-plus-real-resource pattern.
# ---------------------------------------------------------------------------


pytestmark_lifecycle = pytest.mark.integration_real


@pytest.mark.integration_real
class TestRouterStart:
    def test_start_builds_one_speaker_loop_and_marks_running(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.2: start() constructs SpeakerLoop(callback=...,
        # chunk_seconds=..., pid=...) and starts it.
        _patch_speaker_loop(mocker)
        router = Router(pid=12345, device=real_default_device)
        try:
            router.start()
            assert router.is_running is True
            assert len(FakeSpeakerLoop.instances) == 1
            loop = FakeSpeakerLoop.instances[0]
            # Spec F2.2 wiring: pid and chunk_seconds must be forwarded
            # verbatim so the loop captures the right VRChat instance
            # at the right cadence.
            assert loop.pid == 12345
            assert loop.chunk_seconds == pytest.approx(0.02)
        finally:
            router.stop()

    def test_double_start_is_noop(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.3: a second start() with the router already running
        # is a no-op. The simplest observable signature is "no second
        # SpeakerLoop was built".
        _patch_speaker_loop(mocker)
        router = Router(pid=12345, device=real_default_device)
        try:
            router.start()
            router.start()
            assert len(FakeSpeakerLoop.instances) == 1
        finally:
            router.stop()

    def test_speaker_loop_init_failure_propagates(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.2 / EC5: when SpeakerLoop construction raises
        # (e.g. VRChat not running), the same exception MUST surface
        # from Router.start(). The implementation must clean up the
        # player it already opened (Spec F2.2 last bullet); observable
        # signature here is "start raised the original exception AND
        # the router is not in a running state".
        _patch_speaker_loop(mocker)
        FakeSpeakerLoop.init_side_effect = RuntimeError("VRChat is not running")
        router = Router(pid=99999, device=real_default_device)
        with pytest.raises(RuntimeError, match="VRChat is not running"):
            router.start()
        assert router.is_running is False


@pytest.mark.integration_real
class TestRouterStop:
    def test_stop_marks_not_running(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.4: stop() must bring is_running back to False.
        _patch_speaker_loop(mocker)
        router = Router(pid=12345, device=real_default_device)
        router.start()
        router.stop()
        assert router.is_running is False

    def test_double_stop_is_noop(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.5 / F2.12: a second stop() after a clean stop must
        # not raise.
        _patch_speaker_loop(mocker)
        router = Router(pid=12345, device=real_default_device)
        router.start()
        router.stop()
        # If this raises, the contract for "safe to call after clean
        # stop" is broken.
        router.stop()

    def test_stop_without_start_is_noop(self, mocker: MockerFixture) -> None:
        # Spec F2.5: stop on an un-started router is a no-op. Does
        # NOT need the real player because start() was never called.
        _patch_speaker_loop(mocker)
        router = Router(pid=12345, device=_synthetic_device())
        router.stop()
        assert router.is_running is False

    def test_stop_propagates_speaker_loop_exception(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.11 / S5: SpeakerLoop captures worker-thread failures
        # (VRChat died) and re-raises on stop(). Router MUST propagate
        # that exception AFTER cleaning up the player (verified
        # indirectly: a second stop is benign per F2.12).
        _patch_speaker_loop(mocker)
        FakeSpeakerLoop.stop_side_effect = RuntimeError("vrchat dead")
        router = Router(pid=12345, device=real_default_device)
        router.start()
        with pytest.raises(RuntimeError, match="vrchat dead"):
            router.stop()
        # Spec F2.12: second stop must be a clean no-op even though
        # the first surfaced an exception.
        router.stop()
        assert router.is_running is False


@pytest.mark.integration_real
class TestRouterContextManager:
    def test_with_block_enters_and_exits_running_state(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.7: __enter__ calls start(), __exit__ calls stop().
        _patch_speaker_loop(mocker)
        router = Router(pid=12345, device=real_default_device)
        with router as ctx:
            assert ctx is router
            assert router.is_running is True
        assert router.is_running is False

    def test_with_block_propagates_inner_exceptions(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.7: __exit__ does NOT swallow exceptions raised
        # inside the with block. The stop() must still run (verified
        # by is_running == False after).
        _patch_speaker_loop(mocker)
        router = Router(pid=12345, device=real_default_device)

        class _BoomFromUserCode(RuntimeError):
            pass

        with pytest.raises(_BoomFromUserCode):
            with router:
                raise _BoomFromUserCode("user code")
        assert router.is_running is False


@pytest.mark.integration_real
class TestRouterRestartAfterStop:
    def test_start_after_stop_builds_a_fresh_speaker_loop(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.13: stop() then start() must construct a brand new
        # SpeakerLoop (the real SpeakerLoop forbids re-start; the
        # Router wraps a fresh instance to re-enable the relay).
        _patch_speaker_loop(mocker)
        router = Router(pid=12345, device=real_default_device)
        router.start()
        first = FakeSpeakerLoop.instances[0]
        router.stop()
        router.start()
        try:
            assert len(FakeSpeakerLoop.instances) == 2
            assert FakeSpeakerLoop.instances[1] is not first
        finally:
            router.stop()


@pytest.mark.integration_real
class TestRouterStartRollback:
    def test_speaker_loop_start_failure_rolls_back(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F2.2 last bullet / EC10 / EC11: if SpeakerLoop.start()
        # raises after the player was already opened, the player MUST
        # be cleaned up before the exception propagates. Observable
        # signature: after the failure the router is_running == False
        # AND a subsequent stop() is a clean no-op (i.e. the rollback
        # already happened during start, not deferred to stop).
        _patch_speaker_loop(mocker)
        FakeSpeakerLoop.start_side_effect = RuntimeError("speaker start blew up")
        router = Router(pid=12345, device=real_default_device)
        with pytest.raises(RuntimeError, match="speaker start blew up"):
            router.start()
        assert router.is_running is False
        # A clean rollback means the second stop() encounters no live
        # state; no spurious double-close attempt should raise.
        router.stop()


@pytest.mark.integration_real
class TestRouteHelper:
    def test_route_returns_started_router(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F3.1: ``route`` builds a Router AND calls start();
        # returned object is running.
        _patch_speaker_loop(mocker)
        r = route(pid=12345, device=real_default_device)
        try:
            assert isinstance(r, Router)
            assert r.is_running is True
            assert len(FakeSpeakerLoop.instances) == 1
        finally:
            r.stop()

    def test_route_propagates_start_failure(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec F3.2: when start fails, ``route`` MUST NOT return a
        # Router and MUST propagate the original exception.
        _patch_speaker_loop(mocker)
        FakeSpeakerLoop.init_side_effect = RuntimeError("VRChat dead at startup")
        with pytest.raises(RuntimeError, match="VRChat dead at startup"):
            route(pid=12345, device=real_default_device)


@pytest.mark.integration_real
class TestRouteHelperContextUsage:
    def test_with_route_releases_resources(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Spec §8.1 S2: the canonical usage is ``with route(...) as r:``.
        # After the block exits the router must be fully released.
        _patch_speaker_loop(mocker)
        with route(pid=12345, device=real_default_device) as r:
            assert r.is_running is True
        assert r.is_running is False


# ---------------------------------------------------------------------------
# integration_real frame-flow tests (Q1)
#
# These are the T-R8 / T-R9 equivalents. The Q1 decision is to observe
# them through real-player runs rather than direct ``_on_frames`` calls
# or 3rd-party mocks. The strongest available assertion is "the relay
# completes without exception with the documented frame patterns".
# ---------------------------------------------------------------------------


@pytest.mark.integration_real
class TestRouterAgainstRealPlayer:
    def test_relay_runs_without_underrun_with_non_empty_frames(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Q1 / T-R9 / T-R15: with the real default-device player open
        # and FakeSpeakerLoop pushing a handful of non-empty
        # zero-buffer chunks, the relay must complete (no exception,
        # clean shutdown). This is the strongest automated check we
        # can make without either mocking the player (forbidden) or
        # driving real audio output we cannot observe (deferred to e2e).
        _patch_speaker_loop(mocker)
        # Push a small number of non-empty zero-buffer chunks so play()
        # is exercised at least once against the real player.
        FakeSpeakerLoop.frames_per_start = 4
        FakeSpeakerLoop.samples_per_frame = 256
        with route(pid=12345, device=real_default_device) as r:
            assert r.is_running is True
        assert r.is_running is False

    def test_relay_handles_empty_frames_without_crash(
        self,
        mocker: MockerFixture,
        real_default_device: AudioDevice,
    ) -> None:
        # Q1 / T-R8: emit zero-length silence ticks. The Router MUST
        # skip the player call for empty frames per F2.10; if it
        # instead forwarded the empty buffer the underlying soundcard
        # play() would raise on most backends. Observable assertion:
        # the relay completes without exception even with only empty
        # frames flowing through.
        _patch_speaker_loop(mocker)
        # samples_per_frame = 0 produces frames of shape (0, CHANNELS) =
        # the documented silence-tick signal.
        FakeSpeakerLoop.frames_per_start = 4
        FakeSpeakerLoop.samples_per_frame = 0
        with route(pid=12345, device=real_default_device) as r:
            assert r.is_running is True
        assert r.is_running is False
