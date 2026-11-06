"""#6972 — the admission warm cycle starts when the host starts, not at the first call.

The binding is composed while the ASGI app is imported, before any event loop
exists, so ``_arm_warmer`` silently no-op'd and the cycle waited for the first
authority call: the P01 restart at 03:42 stayed cold for four hours and the
07:15 first turn paid a 4.8 s admission (1.4 s warm). The lifespan startup now
fires the first ping on the loop it already has, and the periodic re-arm
(45 s, one journal line per cycle) takes over from there.

These tests pin the startup behaviour and nothing else — the signed warm ping,
its journal line and the periodic cycle stay under
``test_admission_keepwarm_261105.py``. The production sequence is reproduced
literally: the binding is composed **before** a loop exists, then the loop
starts and ``start_admission_warmers`` is called. ``_isolated_registry`` keeps
bindings leaked by earlier suites out of the kick, so the assertions describe
exactly the binding under test.
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx
import pytest

from app import local_admission_binding as binding_module
from app.local_admission_binding import (
    KEEPWARM_METHOD,
    HttpsAdmissionBinding,
    start_admission_warmers,
)

SECRET = "com2-host-admission-secret-0123456789abcdef"
ORIGIN = "https://engine-admission.padiem.internal"
WARM_URL = ORIGIN + "/internal/rpc/" + KEEPWARM_METHOD


class _WarmTarget:
    """The pooled client the binding warms through, with no socket behind it."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, content=None, headers=None, timeout=None) -> httpx.Response:
        self.calls.append(
            {"url": url, "content": content, "headers": dict(headers or {})}
        )
        return httpx.Response(
            200, json={"ok": False, "error": {"code": "engine_entitlement_identity_unavailable"}}
        )


class _BlockingTarget(_WarmTarget):
    """A warm request that stays in flight until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.released = asyncio.Event()

    async def post(self, url: str, content=None, headers=None, timeout=None) -> httpx.Response:
        self.calls.append({"url": url, "content": content, "headers": dict(headers or {})})
        await self.released.wait()
        return httpx.Response(200, json={"ok": False})


@pytest.fixture()
def pooled(monkeypatch):
    def _install(target: _WarmTarget) -> _WarmTarget:
        monkeypatch.setattr(binding_module, "_pooled_client", lambda: target)
        return target

    return _install


@contextlib.contextmanager
def _isolated_registry(binding: HttpsAdmissionBinding):
    """Only the binding under test rides the startup kick.

    ``_LIVE_BINDINGS`` is process-wide and suites above this one may leave
    bindings in it; without the isolation a leaked warmer would fire into this
    test's pooled target and the assertions could not name their subject.
    """

    saved = binding_module._LIVE_BINDINGS[:]
    binding_module._LIVE_BINDINGS[:] = [binding]
    try:
        yield
    finally:
        binding_module._LIVE_BINDINGS[:] = saved


async def _expect_cycles(target: _WarmTarget, count: int, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while len(target.calls) < count:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"only {len(target.calls)} of {count} warm cycles ran")
        await asyncio.sleep(0.005)


def test_the_first_ping_fires_at_startup_before_any_authority_call(pooled) -> None:
    target = pooled(_WarmTarget())
    # Production sequence: composed at import time, before any event loop —
    # so construction arms nothing (that was the four-hour cold window). The
    # period is long here so the window holds exactly the startup kick and
    # nothing else; the periodic re-fire has its own test below.
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=5.0)
    assert target.calls == []

    async def scenario() -> None:
        with _isolated_registry(binding):
            start_admission_warmers()
        await asyncio.sleep(0.05)
        await binding.aclose()

    asyncio.run(scenario())

    assert [call["url"] for call in target.calls] == [WARM_URL]
    assert binding not in binding_module._LIVE_BINDINGS


def test_the_startup_ping_re_fires_periodically(pooled) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=0.02)

    async def scenario() -> None:
        with _isolated_registry(binding):
            start_admission_warmers()
        await _expect_cycles(target, 3)
        await binding.aclose()

    asyncio.run(scenario())

    assert len(target.calls) >= 3
    assert all(call["url"] == WARM_URL for call in target.calls)


def test_zero_keepwarm_stays_cold_at_startup(pooled) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=0)
    assert binding not in binding_module._LIVE_BINDINGS

    async def scenario() -> None:
        with _isolated_registry(binding):
            start_admission_warmers()
        await asyncio.sleep(0.05)

    asyncio.run(scenario())

    assert target.calls == []


def test_shutdown_cancels_the_startup_kick(pooled) -> None:
    target = pooled(_BlockingTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=0.02)

    async def scenario() -> None:
        with _isolated_registry(binding):
            start_admission_warmers()
        await asyncio.sleep(0.02)
        assert len(target.calls) == 1  # the startup kick is in flight
        await binding.aclose()  # cancels the in-flight ping and the cycle
        assert binding._warm_task is None and binding._warm_timer is None
        target.released.set()
        await asyncio.sleep(0.05)

    asyncio.run(scenario())

    assert len(target.calls) == 1  # nothing fired after the shutdown


async def test_a_cycle_a_call_already_started_is_left_alone(pooled) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=0.02)
    try:
        # An authority call arms the periodic cycle itself; the startup hook
        # must not double-fire on top of it.
        await binding.fetch_entitlement_snapshot(
            {"product_id": "b62", "subject": {"subject_type": "user", "subject_id": "x"}}
        )
        assert len(target.calls) == 1  # the real call only
        with _isolated_registry(binding):
            start_admission_warmers()
        assert len(target.calls) == 1  # no instant second cycle
        await _expect_cycles(target, 2)  # the periodic cycle keeps going
    finally:
        await binding.aclose()
