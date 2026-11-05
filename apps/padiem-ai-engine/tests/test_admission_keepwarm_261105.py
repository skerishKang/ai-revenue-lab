"""The host keeps its admission authority warm through the Durable Object.

The first cycle (#6956 follow-up) pinged ``OPTIONS /``: the request reached the
gateway Worker (its own 404 fingerprint came back) but never dispatched — only
``/internal/rpc/<method>`` leaves the gateway — so the Durable Object that owns
the entitlement state and the identity worker behind it stayed cold and the
first turn of a batch still paid the cold cost. The warm ping is now a real
signed ``fetch_entitlement_snapshot`` for a synthetic canonical user: the
authority answers 200 ``ok:false`` ``engine_entitlement_identity_unavailable``
and writes nothing. One journal line per cycle names status and milliseconds
only. These tests pin that cycle and nothing else — the proof, the payload,
the replay retry and the admission decision stay under
``test_local_admission_https_binding_261031.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx
import pytest

from app import local_admission_binding as binding_module
from app.local_admission_binding import (
    ADMISSION_ORIGIN_ENV,
    ADMISSION_SECRET_ENV,
    DEFAULT_KEEPWARM_SECONDS,
    KEEPALIVE_EXPIRY_SECONDS,
    KEEPWARM_METHOD,
    KEEPWARM_SECONDS_ENV,
    HttpsAdmissionBinding,
    admission_binding_for,
)

SECRET = "com2-host-admission-secret-0123456789abcdef"
ORIGIN = "https://engine-admission.padiem.internal"
WARM_URL = ORIGIN + "/internal/rpc/" + KEEPWARM_METHOD
# Pinned literally: the synthetic subject is the side-effect-free contract, so
# a change to it must be a visible test change, not a silent constant edit.
WARM_BODY = json.dumps(
    {
        "product_id": "b62",
        "subject": {"subject_type": "user", "subject_id": "padiem-engine-keepwarm-synthetic"},
    },
    ensure_ascii=False,
    separators=(",", ":"),
).encode("utf-8")
PERIOD = 0.02
JOURNAL_LINE = re.compile(r"^keepwarm status=\d+ ms=\d+(?:\.\d+)?$")


class _WarmTarget:
    """The pooled client the binding warms through, with no socket behind it."""

    def __init__(self, *, fail_first: int = 0, status: int = 200) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_first = fail_first
        self.status = status

    async def post(self, url: str, content=None, headers=None, timeout=None) -> httpx.Response:
        self.calls.append(
            {"url": url, "content": content, "headers": dict(headers or {})}
        )
        if len(self.calls) <= self.fail_first:
            raise httpx.ConnectError(
                "warm target refused", request=httpx.Request("POST", url)
            )
        return httpx.Response(
            self.status,
            json={"ok": False, "error": {"code": "engine_entitlement_identity_unavailable"}},
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


@pytest.fixture()
def journal():
    """Capture the keepwarm line exactly where the host journal receives it."""

    logger = logging.getLogger("padiem_ai_engine.engine_timing")
    seen: list[str] = []
    level = logger.level

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    handler = _Capture()
    logger.addHandler(handler)
    # The host imports app.engine_timing, whose import sets INFO; this suite
    # does not, so mirror the level the journal line is emitted at.
    logger.setLevel(logging.INFO)
    try:
        yield seen
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


async def _expect_cycles(target: _WarmTarget, count: int, timeout: float = 2.0) -> None:
    """Wait for ``count`` warm requests without timing-bound assertions.

    Windows' event-loop clock is coarse; asserting a count after an exact sleep
    would fail on a correct implementation. The cycle is periodic, so the honest
    statement is "this many happen within a generous window".
    """

    deadline = asyncio.get_running_loop().time() + timeout
    while len(target.calls) < count:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"only {len(target.calls)} of {count} warm cycles ran")
        await asyncio.sleep(0.005)


async def test_the_cycle_warms_the_same_origin_path_every_period(pooled) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(target, 3)
    finally:
        await binding.aclose()

    assert [call["url"] for call in target.calls] == [WARM_URL] * len(target.calls)


async def test_the_warm_ping_is_a_signed_snapshot_rpc_for_the_synthetic_subject(
    pooled,
) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(target, 1)
    finally:
        await binding.aclose()

    call = target.calls[0]
    assert call["content"] == WARM_BODY
    headers = call["headers"]
    assert str(headers["x-padiem-service-proof"]).startswith("v2=")
    assert headers["x-padiem-service-id"]
    assert headers["x-padiem-service-at"]
    assert headers["content-type"] == "application/json"


async def test_the_warm_answer_and_its_journal_line_carry_no_payload(pooled, journal) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(target, 2)
    finally:
        await binding.aclose()

    assert journal, "the warm cycle must leave exactly one status line behind"
    for line in journal:
        assert JOURNAL_LINE.fullmatch(line), line
        assert ORIGIN not in line and "padiem-engine-keepwarm-synthetic" not in line
        assert "secret" not in line.lower()


async def test_only_one_warm_cycle_is_outstanding_at_a_time(pooled) -> None:
    target = pooled(_BlockingTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(target, 1)
        assert binding._warm_task is not None and binding._warm_timer is None

        # Several periods pass with a warm request still in flight: no pile-up.
        await asyncio.sleep(PERIOD * 6)
        assert len(target.calls) == 1

        target.released.set()
        await _expect_cycles(target, 2)
    finally:
        await binding.aclose()


async def test_the_cycle_keeps_running_after_a_failed_attempt(pooled, journal) -> None:
    target = pooled(_WarmTarget(fail_first=2))
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(target, 4)
    finally:
        await binding.aclose()

    assert len(target.calls) >= 4
    # A refused connection is a warm outcome too: one line, status 0, no error.
    assert any(line.startswith("keepwarm status=0 ") for line in journal)


async def test_a_non_200_warm_answer_is_logged_and_discarded(pooled, journal) -> None:
    target = pooled(_WarmTarget(status=503))
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(target, 2)
    finally:
        await binding.aclose()

    assert any(line.startswith("keepwarm status=503 ") for line in journal)
    assert len(target.calls) >= 2


async def test_zero_period_schedules_nothing(pooled) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=0)
    try:
        assert binding not in binding_module._LIVE_BINDINGS
        assert binding._warm_timer is None
        await asyncio.sleep(PERIOD * 6)
        assert target.calls == []
    finally:
        await binding.aclose()


async def test_aclose_stops_the_cycle_and_the_registration(pooled) -> None:
    target = pooled(_WarmTarget())
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, keepwarm_seconds=PERIOD)
    assert binding in binding_module._LIVE_BINDINGS
    await _expect_cycles(target, 2)

    await binding.aclose()

    frozen = len(target.calls)
    assert binding not in binding_module._LIVE_BINDINGS
    assert binding._warm_timer is None and binding._warm_task is None
    await asyncio.sleep(PERIOD * 6)
    assert len(target.calls) == frozen


async def test_a_caller_owned_client_is_never_warmed(pooled) -> None:
    target = pooled(_WarmTarget())
    seen: list[str] = []

    class _CallersClient(httpx.AsyncClient):
        async def post(self, url, **kwargs):  # noqa: ANN002, ANN003
            seen.append(url)
            return httpx.Response(200, json={"ok": False})

    caller_client = _CallersClient()
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, client=caller_client)
    await asyncio.sleep(PERIOD * 6)
    await binding.aclose()
    await caller_client.aclose()

    assert seen == [] and target.calls == []


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


class _WarmOnlyBlockingTarget(_WarmTarget):
    """Blocks the warm ping; a real call on the same path answers at once."""

    def __init__(self) -> None:
        super().__init__()
        self.released = asyncio.Event()

    async def post(self, url: str, content=None, headers=None, timeout=None) -> httpx.Response:
        self.calls.append({"url": url, "content": content, "headers": dict(headers or {})})
        if content == WARM_BODY:
            await self.released.wait()
        return httpx.Response(200, json={"ok": False})


async def test_host_boot_arms_the_first_cycle_without_any_call(pooled, journal) -> None:
    """#6895 후속: 호스트는 첫 호출이 아니라 기동 시점에 주기를 점화한다.

    The binding is composed while the ASGI app is imported, before any event
    loop exists, so creation alone cannot schedule the cycle. The lifespan
    startup calls :func:`arm_live_binders` on the running loop, and the first
    warm ping goes out a full period later without a real call — the journal
    showing keepwarm without an engine_timing line around it is how ops proves
    the ignition.
    """

    # The host composes the binding before the loop exists (no running loop in
    # the composing context): create it off the loop, like the host import does.
    binding = await asyncio.to_thread(
        HttpsAdmissionBinding, ORIGIN, SECRET, keepwarm_seconds=PERIOD
    )
    target = pooled(_WarmTarget())
    try:
        assert binding._warm_timer is None and binding._warm_task is None
        binding_module.arm_live_binders()
        await _expect_cycles(target, 1)
    finally:
        await binding.aclose()

    assert journal, "the boot-armed cycle must leave its status line behind"
    for line in journal:
        assert JOURNAL_LINE.fullmatch(line), line


async def test_a_real_call_overlapping_the_boot_armed_cycle_keeps_one_warm_outstanding(
    pooled,
) -> None:
    """A real call that lands during the boot-armed warm cycle adds no second."""

    binding = await asyncio.to_thread(
        HttpsAdmissionBinding, ORIGIN, SECRET, keepwarm_seconds=PERIOD
    )
    target = pooled(_WarmOnlyBlockingTarget())
    try:
        binding_module.arm_live_binders()
        await _expect_cycles(target, 1)
        # The warm request is in flight and no next timer exists alongside it.
        assert binding._warm_task is not None
        assert binding._warm_timer is None

        answer = await binding.fetch_entitlement_snapshot(
            {"product_id": "b62", "subject": {"subject_type": "user", "subject_id": "u1"}}
        )
        assert isinstance(answer, dict)
        warm_calls = [c for c in target.calls if c["content"] == WARM_BODY]
        assert len(warm_calls) == 1, "a warm request must stay single while in flight"
    finally:
        await binding.aclose()


async def test_arm_live_binders_arms_a_binding_created_before_the_loop(pooled) -> None:
    """The public arm point covers every live binding, old or new."""

    binding = await asyncio.to_thread(
        HttpsAdmissionBinding, ORIGIN, SECRET, keepwarm_seconds=PERIOD
    )
    target = pooled(_WarmTarget())
    try:
        assert binding._warm_timer is None
        binding_module.arm_live_binders()
        await _expect_cycles(target, 1)
    finally:
        await binding.aclose()
