"""The host keeps its admission connection warm, so a turn stops paying for a handshake.

Measured on COM2 on 2026-11-05: one snapshot RPC over a fresh connection took
2672 ms while the two that followed over the same keep-alive connection took
635 ms and 653 ms, and `admission_ms` sat at p50 2573 ms because PC turns are more
than a minute apart. `app.local_admission_binding` answers that with a longer
keep-alive expiry plus one warm cycle per binding. These tests pin that cycle and
nothing else — the proof, the payload, the replay retry and the admission decision
stay under ``test_local_admission_https_binding_261031.py``.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import local_admission_binding as binding_module
from app.local_admission_binding import (
    ADMISSION_ORIGIN_ENV,
    ADMISSION_SECRET_ENV,
    DEFAULT_KEEPWARM_SECONDS,
    KEEPALIVE_EXPIRY_SECONDS,
    KEEPWARM_PATH,
    KEEPWARM_SECONDS_ENV,
    HttpsAdmissionBinding,
    admission_binding_for,
)

SECRET = "com2-host-admission-secret-0123456789abcdef"
ORIGIN = "https://engine-admission.padiem.internal"
WARM_URL = ORIGIN + KEEPWARM_PATH
PERIOD = 0.02


class _WarmTarget:
    """The pooled client the binding warms through, with no socket behind it."""

    def __init__(self, *, fail_first: int = 0) -> None:
        self.requests: list[str] = []
        self.fail_first = fail_first

    async def options(self, url: str) -> httpx.Response:
        self.requests.append(url)
        if len(self.requests) <= self.fail_first:
            raise httpx.ConnectError(
                "warm target refused", request=httpx.Request("OPTIONS", url)
            )
        return httpx.Response(404)


class _BlockingTarget(_WarmTarget):
    """A warm request that stays in flight until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.released = asyncio.Event()

    async def options(self, url: str) -> httpx.Response:
        self.requests.append(url)
        await self.released.wait()
        return httpx.Response(404)


@pytest.fixture()
def pooled(monkeypatch):
    def _install(target: _WarmTarget) -> _WarmTarget:
        monkeypatch.setattr(binding_module, "_pooled_client", lambda: target)
        return target

    return _install


async def _expect_cycles(target: _WarmTarget, count: int, timeout: float = 2.0) -> None:
    """Wait for ``count`` warm requests without timing-bound assertions.

    Windows' event-loop clock is coarse; asserting a count after an exact sleep
    would fail on a correct implementation. The cycle is periodic, so the honest
    statement is "this many happen within a generous window".
    """

    deadline = asyncio.get_running_loop().time() + timeout
    while len(target.requests) < count:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"only {len(target.requests)} of {count} warm cycles ran")
        await asyncio.sleep(0.005)


async def test_the_cycle_warms_the_same_origin_path_every_period(pooled) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(target, 3)
    finally:
        await binding.aclose()

    assert target.requests == [WARM_URL] * len(target.requests)


async def test_only_one_warm_cycle_is_outstanding_at_a_time(pooled) -> None:
    target = pooled(_BlockingTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(target, 1)
        assert binding._warm_task is not None and binding._warm_timer is None

        # Several periods pass with a warm request still in flight: no pile-up.
        await asyncio.sleep(PERIOD * 6)
        assert len(target.requests) == 1

        target.released.set()
        await _expect_cycles(target, 2)
    finally:
        await binding.aclose()


async def test_the_cycle_keeps_running_after_a_failed_attempt(pooled) -> None:
    target = pooled(_WarmTarget(fail_first=2))
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(target, 4)
    finally:
        await binding.aclose()

    assert len(target.requests) >= 4


async def test_zero_period_schedules_nothing(pooled) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=0)
    try:
        assert binding not in binding_module._LIVE_BINDINGS
        assert binding._warm_timer is None
        await asyncio.sleep(PERIOD * 6)
        assert target.requests == []
    finally:
        await binding.aclose()


async def test_aclose_stops_the_cycle_and_the_registration(pooled) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    assert binding in binding_module._LIVE_BINDINGS
    await _expect_cycles(target, 2)

    await binding.aclose()

    frozen = len(target.requests)
    assert binding not in binding_module._LIVE_BINDINGS
    assert binding._warm_timer is None and binding._warm_task is None
    await asyncio.sleep(PERIOD * 6)
    assert len(target.requests) == frozen


async def test_a_caller_owned_client_is_never_warmed(pooled) -> None:
    target = pooled(_WarmTarget())
    seen: list[str] = []

    class _CallersClient(httpx.AsyncClient):
        async def options(self, url, **kwargs):  # noqa: ANN002, ANN003
            seen.append(url)
            return httpx.Response(404)

    caller_client = _CallersClient()
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, client=caller_client)
    await asyncio.sleep(PERIOD * 6)
    await binding.aclose()
    await caller_client.aclose()

    assert seen == [] and target.requests == []


def test_the_pooled_client_widens_keepalive_and_adds_http2_only_when_h2_exists(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    real_client = httpx.AsyncClient

    class _CapturingClient(real_client):
        def __init__(self, *args, **kwargs) -> None:
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _CapturingClient)
    monkeypatch.setattr(binding_module, "_POOLED_CLIENTS", {})

    async def _build() -> None:
        await binding_module._pooled_client().aclose()

    asyncio.run(_build())

    assert captured["limits"].keepalive_expiry == KEEPALIVE_EXPIRY_SECONDS == 300.0
    # The RPC timeout is not part of this change.
    assert captured["timeout"] == binding_module.DEFAULT_TIMEOUT_SECONDS == 15.0
    assert ("http2" in captured) is binding_module._http2_available()


def test_the_warm_period_is_an_operational_number_with_a_safe_default() -> None:
    values = {ADMISSION_ORIGIN_ENV: ORIGIN, ADMISSION_SECRET_ENV: SECRET}

    def _period(raw: str | None) -> float:
        configured = dict(values) if raw is None else {**values, KEEPWARM_SECONDS_ENV: raw}
        return admission_binding_for(configured)["CONTROL_PLANE_ENGINE_ADMISSION"]._keepwarm

    assert _period(None) == DEFAULT_KEEPWARM_SECONDS == 45.0
    assert _period("7") == 7.0
    assert _period("0") == 0.0
    # A typo must not drop the host back to a cold handshake, nor fail the boot.
    assert _period("soon") == DEFAULT_KEEPWARM_SECONDS
    assert _period("-3") == DEFAULT_KEEPWARM_SECONDS
