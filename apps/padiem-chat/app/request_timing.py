"""Request-local wall-clock spans; fixed names, no request or SQL material."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock
from time import perf_counter

STAGES = ('auth', 'edge', 'identity', 'p01', 'b14', 'queue',
          'sqlite_wait', 'sqlite_execute')


class RequestTiming:
    def __init__(self):
        self._values = dict.fromkeys(STAGES, 0.0)
        self._lock = Lock()

    def add(self, stage, duration_ms):
        if stage not in self._values:
            return
        with self._lock:
            self._values[stage] += max(0.0, float(duration_ms))

    def snapshot(self):
        with self._lock:
            return {name: round(value, 3) for name, value in self._values.items()}


_CURRENT: ContextVar[RequestTiming | None] = ContextVar('chat_request_timing', default=None)


def start_timing():
    timing = RequestTiming()
    return timing, _CURRENT.set(timing)


def reset_timing(token):
    _CURRENT.reset(token)


def record_duration(stage: str, duration_ms: float) -> None:
    timing = _CURRENT.get()
    if timing is not None:
        timing.add(stage, duration_ms)


@contextmanager
def measure(stage: str):
    started = perf_counter()
    try:
        yield
    finally:
        record_duration(stage, (perf_counter() - started) * 1000)


def timed_async(stage: str):
    def decorate(function):
        @wraps(function)
        async def call(*args, **kwargs):
            with measure(stage):
                return await function(*args, **kwargs)
        return call
    return decorate
