"""Loopback-UDP fixtures shared across :mod:`vrcpilot.osc` tests.

These tests follow the *integration-real* strategy: a real
:class:`pythonosc.osc_server.ThreadingOSCUDPServer` is bound to an
ephemeral loopback port and a real :class:`vrcpilot.osc.OscSender`
(constructed via its public constructor with the loopback host/port)
sends to it. No 3rd-party surfaces (``SimpleUDPClient``,
``time.sleep``) are mocked: the spec is "the bytes that arrive on the
wire are what VRChat will see", so we verify directly against the wire.

The :class:`Recorder` helper records every received OSC message as
``(address, args)`` tuples. ``args`` preserves wire-level Python types
(``int``, ``float``, ``bool``, ``str``) which lets us distinguish
``send_int`` (OSC ``i`` tag) from ``send_float`` (OSC ``f`` tag).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

from vrcpilot.osc.sender import OscSender


@dataclass
class Recorder:
    """Collects OSC messages received over the loopback server.

    The server thread appends ``(address, tuple(args))`` to
    :attr:`messages` for every datagram. Tests poll
    :meth:`wait_for` to synchronize on the expected message count
    without relying on arbitrary ``time.sleep`` durations.
    """

    messages: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _condition: threading.Condition = field(init=False)

    def __post_init__(self) -> None:
        self._condition = threading.Condition(self._lock)

    def record(self, address: str, *args: Any) -> None:
        """Dispatcher handler — append a received message, notify waiters."""
        with self._condition:
            self.messages.append((address, args))
            self._condition.notify_all()

    def wait_for(self, count: int, timeout: float = 2.0) -> None:
        """Block until at least ``count`` messages have arrived.

        Raises :class:`AssertionError` (via pytest) if the timeout
        elapses first — surfaces "no datagram arrived" as a clean test
        failure rather than an indefinite hang.
        """
        with self._condition:
            ok = self._condition.wait_for(
                lambda: len(self.messages) >= count, timeout=timeout
            )
        if not ok:
            raise AssertionError(
                f"timed out waiting for {count} OSC messages; "
                f"received {len(self.messages)}: {self.messages}"
            )

    def clear(self) -> None:
        """Drop all recorded messages — useful between sub-scenarios."""
        with self._condition:
            self.messages.clear()


@dataclass
class LoopbackOsc:
    """A live loopback OSC server bound to ``127.0.0.1`` on an ephemeral port.

    ``recorder`` collects everything that arrives. ``host`` / ``port``
    are the address the running server is listening on.
    """

    recorder: Recorder
    host: str
    port: int


@pytest.fixture
def loopback_osc() -> Iterator[LoopbackOsc]:
    """Spawn a real OSC server on a loopback ephemeral port for the test.

    The server is shut down and the socket closed at teardown. Using
    port ``0`` makes parallel test runs collision-free.
    """
    recorder = Recorder()
    dispatcher = Dispatcher()
    dispatcher.set_default_handler(recorder.record)
    server = ThreadingOSCUDPServer(("127.0.0.1", 0), dispatcher)
    host, port = server.server_address[0], server.server_address[1]
    # ``poll_interval`` controls how often ``serve_forever`` checks the
    # shutdown flag; the stdlib default (0.5s) makes every test
    # teardown wait that long. 10ms is plenty fast for UDP delivery
    # but keeps teardown effectively instant.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield LoopbackOsc(recorder=recorder, host=host, port=port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


@pytest.fixture
def sender(loopback_osc: LoopbackOsc) -> OscSender:
    """An :class:`OscSender` pointed at the loopback OSC server.

    Constructed via the documented public ``host`` / ``port``
    constructor (no ``client=`` injection), so the real
    :class:`pythonosc.udp_client.SimpleUDPClient` is exercised
    end-to-end.
    """
    return OscSender(host=loopback_osc.host, port=loopback_osc.port)
