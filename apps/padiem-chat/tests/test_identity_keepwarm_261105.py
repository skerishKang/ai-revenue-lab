"""The host keeps the identity authority warm, so a turn stops paying the cold cost.

The pooled client (#6613/#6460 4-1) already survives the scope-cache window,
but a quiet host still lets the connection and the identity Worker's isolate go
cold, and the first identity RPC of a batch pays that again. The binding
therefore runs an opt-in warm cycle (``PADIEM_CHAT_IDENTITY_KEEPWARM_SECONDS``,
default 45, 0 off): one read-only ``resolve_product_user_for_subject`` for a
synthetic canonical subject per period. The Durable Object reads the
``canonical_product_identity_link`` row for that exact pair, fails closed on a
missing one and writes nothing (#3247), so the answer — and any failure — is
discarded. These tests pin the cycle and nothing else; the proof, the payload
and the authority adapter stay under the local_service_bridge and identity
test files.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from app.local_service_bridge import (
    IDENTITY_KEEPWARM_METHOD,
    IDENTITY_KEEPWARM_PAYLOAD,
    HttpRpcBinding,
)

SECRET = "com2-host-identity-secret-0123456789abcdef"
ORIGIN = "https://identity.example.test"
WARM_URL = ORIGIN + "/internal/rpc/" + IDENTITY_KEEPWARM_METHOD
PERIOD = 0.02


class _WarmClient:
    """The pooled client the binding warms through, with no socket behind it.

    The one real call each test makes to arm the cycle must always succeed, so
    failures and blocking apply to warm attempts only.
    """

    def __init__(self, *, fail_first: int = 0) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_first = fail_first
        self.warm_attempts = 0

    def _record(self, url: str, content, headers) -> None:
        self.calls.append({"url": url, "content": content, "headers": dict(headers or {})})

    def _warm_failure(self, url: str) -> bool:
        if url != WARM_URL:
            return False
        self.warm_attempts += 1
        return self.warm_attempts <= self.fail_first

    async def post(self, url: str, content=None, headers=None) -> httpx.Response:
        self._record(url, content, headers)
        if self._warm_failure(url):
            raise httpx.ConnectError(
                "warm target refused", request=httpx.Request("POST", url)
            )
        return httpx.Response(
            200, json={"ok": False, "error": {"code": "canonical_product_identity_link_missing"}}
        )


class _BlockingClient(_WarmClient):
    """A warm request that stays in flight until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.released = asyncio.Event()

    async def post(self, url: str, content=None, headers=None) -> httpx.Response:
        self._record(url, content, headers)
        if url == WARM_URL:
            await self.released.wait()
        return httpx.Response(200, json={"ok": False})


async def _expect_cycles(target: _WarmClient, count: int, timeout: float = 2.0) -> None:
    """Wait for ``count`` warm requests without timing-bound assertions.

    Windows' event-loop clock is coarse; the cycle is periodic, so the honest
    statement is "this many happen within a generous window". Only warm calls
    count — the real call that arms the cycle is not one.
    """

    deadline = asyncio.get_running_loop().time() + timeout

    def _warm_seen() -> int:
        return len([call for call in target.calls if call["url"] == WARM_URL])

    while _warm_seen() < count:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"only {_warm_seen()} of {count} warm cycles ran")
        await asyncio.sleep(0.005)


async def test_the_cycle_fires_one_warm_rpc_every_period() -> None:
    client = _WarmClient()
    binding = HttpRpcBinding(
        ORIGIN, SECRET, client=client, keepwarm_seconds=PERIOD
    )
    try:
        # The cycle arms on the first real RPC, on the loop it already runs on.
        await binding.resolve_current_auth_session({"product_id": "b62", "product_user_id": "u1"})
        await _expect_cycles(client, 3)
    finally:
        await binding.aclose()

    warm_urls = [call["url"] for call in client.calls if call["url"] == WARM_URL]
    assert len(warm_urls) >= 3
    # The one real call the test made is the only non-warm traffic.
    real = [call for call in client.calls if call["url"] != WARM_URL]
    assert [call["url"] for call in real] == [
        ORIGIN + "/internal/rpc/resolve_current_auth_session"
    ]


async def test_the_warm_rpc_is_the_readonly_reverse_lookup_for_a_synthetic_subject() -> None:
    client = _WarmClient()
    binding = HttpRpcBinding(
        ORIGIN, SECRET, client=client, keepwarm_seconds=PERIOD
    )
    try:
        await binding.resolve_current_auth_session({"product_id": "b62", "product_user_id": "u1"})
        await _expect_cycles(client, 1)
    finally:
        await binding.aclose()

    warm = next(call for call in client.calls if call["url"] == WARM_URL)
    body = json.loads(warm["content"])  # type: ignore[arg-type]
    assert body == {
        "product_id": "b62",
        "canonical_subject_id": "padiem-chat-identity-keepwarm-synthetic",
    }
    assert IDENTITY_KEEPWARM_PAYLOAD == body
    headers = warm["headers"]
    assert str(headers["x-padiem-service-proof"]).startswith("v2=")
    assert headers["x-padiem-service-id"]
    assert headers["x-padiem-service-at"]


async def test_the_cycle_keeps_running_after_a_failed_attempt() -> None:
    client = _WarmClient(fail_first=2)
    binding = HttpRpcBinding(
        ORIGIN, SECRET, client=client, keepwarm_seconds=PERIOD
    )
    try:
        await binding.resolve_current_auth_session({"product_id": "b62", "product_user_id": "u1"})
        await _expect_cycles(client, 4)
    finally:
        await binding.aclose()

    assert len(client.calls) >= 4


async def test_zero_period_schedules_nothing() -> None:
    client = _WarmClient()
    binding = HttpRpcBinding(
        ORIGIN, SECRET, client=client, keepwarm_seconds=0
    )
    try:
        await binding.resolve_current_auth_session({"product_id": "b62", "product_user_id": "u1"})
        assert binding._warm_timer is None
        await asyncio.sleep(PERIOD * 6)
        # Exactly the one real call; no warm cycle ever started.
        assert len(client.calls) == 1
    finally:
        await binding.aclose()


async def test_aclose_stops_the_cycle() -> None:
    client = _WarmClient()
    binding = HttpRpcBinding(
        ORIGIN, SECRET, client=client, keepwarm_seconds=PERIOD
    )
    await binding.resolve_current_auth_session({"product_id": "b62", "product_user_id": "u1"})
    await _expect_cycles(client, 2)

    await binding.aclose()

    frozen = len(client.calls)
    assert binding._warm_timer is None and binding._warm_task is None
    await asyncio.sleep(PERIOD * 6)
    assert len(client.calls) == frozen


async def test_only_one_warm_cycle_is_outstanding_at_a_time() -> None:
    client = _BlockingClient()
    binding = HttpRpcBinding(
        ORIGIN, SECRET, client=client, keepwarm_seconds=PERIOD
    )
    try:
        await binding.resolve_current_auth_session({"product_id": "b62", "product_user_id": "u1"})
        await _expect_cycles(client, 1)
        assert binding._warm_task is not None and binding._warm_timer is None

        # Several periods pass with a warm request still in flight: no pile-up.
        await asyncio.sleep(PERIOD * 6)
        warm_calls = [call for call in client.calls if call["url"] == WARM_URL]
        assert len(warm_calls) == 1

        client.released.set()
        await _expect_cycles(client, 2)
    finally:
        await binding.aclose()


async def test_a_warm_answer_that_is_not_ok_is_still_just_warming() -> None:
    class _NotOkClient(_WarmClient):
        async def post(self, url: str, content=None, headers=None) -> httpx.Response:
            self.calls.append({"url": url, "content": content, "headers": dict(headers or {})})
            return httpx.Response(200, json={"ok": False})

    client = _NotOkClient()
    binding = HttpRpcBinding(
        ORIGIN, SECRET, client=client, keepwarm_seconds=PERIOD
    )
    try:
        await binding.resolve_current_auth_session({"product_id": "b62", "product_user_id": "u1"})
        await _expect_cycles(client, 2)
    finally:
        await binding.aclose()

    assert len([call for call in client.calls if call["url"] == WARM_URL]) >= 2


async def test_the_cycle_arms_at_creation_without_any_real_call() -> None:
    """#6895 후속: 호스트는 첫 호출이 아니라 바인딩 생성(기동) 시점에 점화한다.

    The binding is composed while the host app is built, so the first warm ping
    goes out a full period after boot without any real RPC — a journal of
    identity_keepwarm lines with no turn around them is how ops proves the
    ignition.
    """

    client = _WarmClient()
    binding = HttpRpcBinding(ORIGIN, SECRET, client=client, keepwarm_seconds=PERIOD)
    try:
        await _expect_cycles(client, 1)
    finally:
        await binding.aclose()

    warm_urls = [call["url"] for call in client.calls if call["url"] == WARM_URL]
    assert len(warm_urls) >= 1
    # No real RPC was ever made: every recorded call is the warm ping.
    assert len(client.calls) == len(warm_urls)


async def test_every_cycle_leaves_one_identity_keepwarm_status_line() -> None:
    """운영 증명: 주기마다 값만 담은 저널 한 줄이 남는다."""

    import logging
    import re

    seen: list[str] = []
    logger = logging.getLogger("padiem_chat.identity_keepwarm")

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    line_re = re.compile(r"^identity_keepwarm status=\d+ ms=\d+(?:\.\d+)?$")
    handler = _Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        client = _WarmClient(fail_first=1)
        binding = HttpRpcBinding(ORIGIN, SECRET, client=client, keepwarm_seconds=PERIOD)
        try:
            await _expect_cycles(client, 3)
        finally:
            await binding.aclose()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)

    assert seen, "each warm cycle must leave exactly one status line"
    for line in seen:
        assert line_re.fullmatch(line), line
        assert ORIGIN not in line and "padiem-chat-identity-keepwarm-synthetic" not in line
        assert "secret" not in line.lower()


async def test_a_real_call_overlapping_the_armed_cycle_keeps_one_warm_outstanding() -> None:
    """A real RPC landing during the warm request adds no second warm."""

    client = _BlockingClient()
    binding = HttpRpcBinding(ORIGIN, SECRET, client=client, keepwarm_seconds=PERIOD)
    try:
        # The cycle armed at creation is already in flight.
        await _expect_cycles(client, 1)
        assert binding._warm_task is not None
        assert binding._warm_timer is None

        answer = await binding.resolve_current_auth_session(
            {"product_id": "b62", "product_user_id": "u1"}
        )
        assert isinstance(answer, dict)
        warm_calls = [call for call in client.calls if call["url"] == WARM_URL]
        assert len(warm_calls) == 1, "a warm request must stay single while in flight"
    finally:
        await binding.aclose()
