"""Process-related test doubles.

Stand-ins for ``psutil.Process`` (returned by ``psutil.process_iter``)
and ``subprocess.Popen``. Both are duck-type compatible with the real
classes so production code can be patched in place.
"""

from __future__ import annotations

import os
from typing import Self


class FakeProcess:
    """Stand-in for ``psutil.Process``.

    Production code reads ``proc.info["name"]``, ``proc.pid``,
    ``proc.create_time()`` and calls ``proc.kill()`` — nothing else.
    ``kill_raises`` simulates a race where the process exits between
    ``process_iter`` enumeration and ``kill()``;
    ``create_time_raises`` simulates the analogous race on
    ``create_time()`` (e.g. ``psutil.NoSuchProcess`` /
    ``psutil.AccessDenied``).
    """

    def __init__(
        self,
        *,
        name: str,
        pid: int = 4242,
        kill_raises: BaseException | None = None,
        create_time: float = 0.0,
        create_time_raises: BaseException | None = None,
    ) -> None:
        self.info: dict[str, object] = {"name": name}
        self.pid = pid
        self.kill_calls: int = 0
        self._kill_raises = kill_raises
        self._create_time = create_time
        self._create_time_raises = create_time_raises

    def kill(self) -> None:
        self.kill_calls += 1
        if self._kill_raises is not None:
            raise self._kill_raises

    def create_time(self) -> float:
        if self._create_time_raises is not None:
            raise self._create_time_raises
        return self._create_time


class FakePopen:
    """Stand-in for ``subprocess.Popen``.

    Records the argv and kwargs of every invocation on the class so
    tests can assert what was *about* to be spawned without actually
    invoking Steam. Each new instance also surfaces its own
    :attr:`args` / :attr:`kwargs` for fine-grained assertions.

    Use as a class-level patch:

        mocker.patch("vrcpilot.process.subprocess.Popen", FakePopen)
        FakePopen.reset()  # clear class state between tests

    Then introspect via ``FakePopen.last_argv`` / ``FakePopen.calls``.
    """

    calls: list[tuple[list[str], dict[str, object]]] = []
    last_argv: list[str] | None = None
    last_kwargs: dict[str, object] = {}

    def __init__(self, args: list[str], **kwargs: object) -> None:
        self.args = list(args)
        self.kwargs = dict(kwargs)
        self.pid = os.getpid()
        self.returncode: int | None = None
        type(self).calls.append((self.args, self.kwargs))
        type(self).last_argv = self.args
        type(self).last_kwargs = self.kwargs

    @classmethod
    def reset(cls) -> None:
        """Clear class-level state.

        Call from per-test fixture setup.
        """
        cls.calls = []
        cls.last_argv = None
        cls.last_kwargs = {}

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info
