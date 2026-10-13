"""B14 completed-response read boundary (#4379, CLAW3).

Proves whether generic / OpenCode-Go / legacy-BYOK completed JSON paths bound
the upstream body BEFORE decoding it into RAM, and pins that healthy long
answers are never truncated (byte resource guard != model output ceiling).

All outbound calls use synthetic transports. No provider traffic.
Go models stay OFF; ZansLab untouched.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot import provider as byok
from app.pilot import opencode_go_wire as go
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.errors import (
    MalformedUpstreamResponse,
    UpstreamAuthFailed,
    UpstreamResponseTooLarge,
    UpstreamTimeout,
)

import tracemalloc

CAP = plat.MAX_RESPONSE_BYTES  # 1MiB error/SSE frame guard (not a token ceiling)
COMPLETED_CAP = plat.MAX_COMPLETED_RESPONSE_BYTES  # finite Worker JSON resource budget
CHUNK = 64 * 1024
OVER_TAIL = 16 * 1024
FLOOD_OVER = 16 * CHUNK  # 1MiB over cap: full buffering is measurably unbounded
LONG_OK = 256 * 1024

MOCK_ID = "test-bounds/kilo-protocol-chat"
MOCK_UPSTREAM = "test-bounds/kilo-protocol-response"
MOCK_PROVIDER = "test-bounds"
MOCK_ORIGIN = "https://bounds-synthetic.example/v1"

GO_MODEL = "opencode-go/longcat-2.5-preview-free"
GO_UPSTREAM = "longcat-2.5-preview-free"
GO_SESSION = "chat_0123456789abcdef0123456789abcdef"
GO_TURNS = [{"role": "user", "content": "Say hi."}]


@pytest.fixture()
def live_keyless_route(monkeypatch):
    """Synthetic keyless live route; restores mock mode afterwards."""
    import sys
    from dataclasses import replace

    import app.pilot.catalog as cat
    from app.pilot import platform_secrets as ps

    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved_mode = rcfg.provider_mode
    rcfg.provider_mode = "live"
    historical = next(iter(cat.CATALOG_BY_ID.values()))
    synthetic = replace(
        historical,
        model_id=MOCK_ID,
        upstream_model=MOCK_UPSTREAM,
        display_name="Synthetic completed-bounds fixture",
        provider="Synthetic test-only gateway",
        platform_provider_id=MOCK_PROVIDER,
        capabilities=frozenset({"chat", "free"}),
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
    )
    spec = ps.PlatformProviderSpec(
        provider_id=MOCK_PROVIDER,
        credential_source=ps.CredentialSource.NONE,
        credential_binding_name="",
        base_origin=MOCK_ORIGIN,
        allowed_hosts=("bounds-synthetic.example",),
    )
    monkeypatch.setitem(cat.CATALOG_BY_ID, MOCK_ID, synthetic)
    monkeypatch.setitem(ps._PLATFORM_PROVIDERS, MOCK_PROVIDER, spec)
    current = sys.modules[__name__]
    monkeypatch.setattr(current, "MOCK_ID", MOCK_ID)
    monkeypatch.setattr(current, "MOCK_UPSTREAM", MOCK_UPSTREAM)
    yield
    rcfg.provider_mode = saved_mode


@pytest.fixture()
def go_auth_stub(monkeypatch):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)

    async def synthetic_auth(h, wire):
        return {**h, "Authorization": "Bearer synthetic-test-credential"}

    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)


def _completed_doc(answer: str, model: str = MOCK_UPSTREAM) -> dict:
    return {
        "id": "cmpl-bounds",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
    }


class ChunkCountingTransport(httpx.AsyncBaseTransport):
    """Serves a fixed payload in fixed chunks; records bytes actually pulled."""

    def __init__(self, payload: bytes, *, status: int = 200, headers: dict | None = None):
        self._payload = payload
        self.status = status
        self.headers = headers or {"content-type": "application/json"}
        self.served_bytes = 0
        self.calls = 0
        self.last_request_body_model: str | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        try:
            self.last_request_body_model = json.loads(request.content).get("model")
        except ValueError:
            self.last_request_body_model = None
        state = self

        async def gen():
            for off in range(0, len(state._payload), CHUNK):
                piece = state._payload[off : off + CHUNK]
                state.served_bytes += len(piece)
                yield piece

        return httpx.Response(self.status, headers=self.headers, content=gen())


def _go_doc(answer: str) -> dict:
    return {
        "model": GO_UPSTREAM,
        "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1},
    }


# --- generic platform completed -------------------------------------------

@pytest.mark.asyncio
async def test_generic_oversize_completed_is_resource_error_not_success(live_keyless_route):
    payload = json.dumps(_completed_doc("A" * (COMPLETED_CAP + OVER_TAIL))).encode()
    assert len(payload) > COMPLETED_CAP
    seen: list = []

    def handle(req):
        seen.append(req)
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    with pytest.raises(UpstreamResponseTooLarge):
        await plat.call_platform_chat_completions(
            model_id=MOCK_ID,
            upstream_model=MOCK_UPSTREAM,
            provider="Synthetic test-only gateway",
            platform_provider_id=MOCK_PROVIDER,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=httpx.MockTransport(handle),
        )
    assert len(seen) == 1  # no retry on oversize
    assert json.loads(seen[0].content)["model"] == MOCK_UPSTREAM  # exact ID, no fallback


@pytest.mark.asyncio
async def test_generic_completed_read_stops_at_cap(live_keyless_route):
    payload = json.dumps(_completed_doc("A" * (COMPLETED_CAP + FLOOD_OVER))).encode()
    transport = ChunkCountingTransport(payload)
    with pytest.raises(UpstreamResponseTooLarge):
        await plat.call_platform_chat_completions(
            model_id=MOCK_ID,
            upstream_model=MOCK_UPSTREAM,
            provider="Synthetic test-only gateway",
            platform_provider_id=MOCK_PROVIDER,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=transport,
        )
    assert transport.calls == 1
    assert transport.last_request_body_model == MOCK_UPSTREAM
    assert transport.served_bytes <= COMPLETED_CAP + CHUNK  # never pulls the whole body into RAM


@pytest.mark.asyncio
async def test_generic_healthy_long_answer_accepted_verbatim(live_keyless_route):
    answer = "B" * LONG_OK

    def handle(req):
        return httpx.Response(200, json=_completed_doc(answer))

    result = await plat.call_platform_chat_completions(
        model_id=MOCK_ID,
        upstream_model=MOCK_UPSTREAM,
        provider="Synthetic test-only gateway",
        platform_provider_id=MOCK_PROVIDER,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=32,
        transport=httpx.MockTransport(handle),
    )
    assert result["choices"][0]["message"]["content"] == answer


@pytest.mark.asyncio
async def test_generic_declared_content_length_over_cap_rejected(live_keyless_route):
    small = json.dumps(_completed_doc("tiny")).encode()
    transport = ChunkCountingTransport(
        small, headers={"content-type": "application/json", "content-length": str(COMPLETED_CAP + 1)}
    )
    with pytest.raises(UpstreamResponseTooLarge):
        await plat.call_platform_chat_completions(
            model_id=MOCK_ID,
            upstream_model=MOCK_UPSTREAM,
            provider="Synthetic test-only gateway",
            platform_provider_id=MOCK_PROVIDER,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=transport,
        )
    assert transport.served_bytes == 0  # announced-huge body is never pulled


@pytest.mark.asyncio
async def test_generic_truncated_body_is_malformed_not_success(live_keyless_route):
    def handle(req):
        return httpx.Response(200, content=b'{"choices": [{"message": {"cont', headers={"content-type": "application/json"})

    with pytest.raises(MalformedUpstreamResponse):
        await plat.call_platform_chat_completions(
            model_id=MOCK_ID,
            upstream_model=MOCK_UPSTREAM,
            provider="Synthetic test-only gateway",
            platform_provider_id=MOCK_PROVIDER,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=httpx.MockTransport(handle),
        )


@pytest.mark.asyncio
async def test_generic_401_fails_auth_without_json_decode(live_keyless_route):
    seen: list = []

    def handle(req):
        seen.append(req)
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    with pytest.raises(UpstreamAuthFailed):
        await plat.call_platform_chat_completions(
            model_id=MOCK_ID,
            upstream_model=MOCK_UPSTREAM,
            provider="Synthetic test-only gateway",
            platform_provider_id=MOCK_PROVIDER,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=httpx.MockTransport(handle),
        )
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_generic_oversize_error_body_is_resource_error(live_keyless_route):
    # The error-inspection path is byte-bounded too: a huge error body trips
    # the resource guard instead of buffering fully for classification.
    big = b'{"error": {"message": "' + b"X" * (CAP + OVER_TAIL) + b'"}}'

    def handle(req):
        return httpx.Response(401, content=big, headers={"content-type": "application/json"})

    with pytest.raises(UpstreamResponseTooLarge):
        await plat.call_platform_chat_completions(
            model_id=MOCK_ID,
            upstream_model=MOCK_UPSTREAM,
            provider="Synthetic test-only gateway",
            platform_provider_id=MOCK_PROVIDER,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=httpx.MockTransport(handle),
        )


# --- OpenCode Go completed -------------------------------------------------

@pytest.mark.asyncio
async def test_go_oversize_completed_is_resource_error(go_auth_stub):
    payload = json.dumps(_go_doc("A" * (COMPLETED_CAP + OVER_TAIL))).encode()
    assert len(payload) > COMPLETED_CAP
    seen: list = []

    def handle(req):
        seen.append(req)
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    with pytest.raises(UpstreamResponseTooLarge):
        await go.call_go_model(
            model_id=GO_MODEL,
            upstream_model=GO_UPSTREAM,
            messages=GO_TURNS,
            session_id=GO_SESSION,
            max_tokens=32,
            transport=httpx.MockTransport(handle),
        )
    assert len(seen) == 1
    assert json.loads(seen[0].content)["model"] == GO_UPSTREAM


@pytest.mark.asyncio
async def test_go_completed_read_stops_at_cap(go_auth_stub):
    payload = json.dumps(_go_doc("A" * (COMPLETED_CAP + FLOOD_OVER))).encode()
    transport = ChunkCountingTransport(payload)
    with pytest.raises(UpstreamResponseTooLarge):
        await go.call_go_model(
            model_id=GO_MODEL,
            upstream_model=GO_UPSTREAM,
            messages=GO_TURNS,
            session_id=GO_SESSION,
            max_tokens=32,
            transport=transport,
        )
    assert transport.calls == 1
    assert transport.last_request_body_model == GO_UPSTREAM
    assert transport.served_bytes <= COMPLETED_CAP + CHUNK


@pytest.mark.asyncio
async def test_go_healthy_long_answer_accepted_verbatim(go_auth_stub):
    answer = "C" * LONG_OK

    def handle(req):
        return httpx.Response(200, json=_go_doc(answer))

    result = await go.call_go_model(
        model_id=GO_MODEL,
        upstream_model=GO_UPSTREAM,
        messages=GO_TURNS,
        session_id=GO_SESSION,
        max_tokens=32,
        transport=httpx.MockTransport(handle),
    )
    assert result["choices"][0]["message"]["content"] == answer


# --- legacy BYOK completed -------------------------------------------------

BYOK_URL = "https://byok-synthetic.example"
BYOK_MODEL = "byok-synthetic-model"


@pytest.mark.asyncio
async def test_byok_oversize_completed_is_resource_error():
    payload = json.dumps(_completed_doc("A" * (COMPLETED_CAP + OVER_TAIL), model=BYOK_MODEL)).encode()
    assert len(payload) > COMPLETED_CAP
    seen: list = []

    def handle(req):
        seen.append(req)
        assert req.url.host == "byok-synthetic.example"
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    with pytest.raises(UpstreamResponseTooLarge):
        await byok.call_chat_completions(
            "sk-test-byok-0123456789abcdef",
            [{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=httpx.MockTransport(handle),
            base_url=BYOK_URL,
            upstream_model=BYOK_MODEL,
            timeout_seconds=30,
            response_model=BYOK_MODEL,
        )
    assert len(seen) == 1
    assert json.loads(seen[0].content)["model"] == BYOK_MODEL


@pytest.mark.asyncio
async def test_byok_completed_read_stops_at_cap():
    payload = json.dumps(_completed_doc("A" * (COMPLETED_CAP + FLOOD_OVER), model=BYOK_MODEL)).encode()
    transport = ChunkCountingTransport(payload)
    with pytest.raises(UpstreamResponseTooLarge):
        await byok.call_chat_completions(
            "sk-test-byok-0123456789abcdef",
            [{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=transport,
            base_url=BYOK_URL,
            upstream_model=BYOK_MODEL,
            timeout_seconds=30,
            response_model=BYOK_MODEL,
        )
    assert transport.calls == 1
    assert transport.last_request_body_model == BYOK_MODEL
    assert transport.served_bytes <= COMPLETED_CAP + CHUNK


@pytest.mark.asyncio
async def test_byok_healthy_long_answer_accepted_verbatim():
    answer = "D" * LONG_OK

    def handle(req):
        return httpx.Response(200, json=_completed_doc(answer, model=BYOK_MODEL))

    result = await byok.call_chat_completions(
        "sk-test-byok-0123456789abcdef",
        [{"role": "user", "content": "hi"}],
        max_tokens=32,
        transport=httpx.MockTransport(handle),
        base_url=BYOK_URL,
        upstream_model=BYOK_MODEL,
        timeout_seconds=30,
        response_model=BYOK_MODEL,
    )
    assert result["choices"][0]["message"]["content"] == answer


@pytest.mark.asyncio
async def test_byok_401_with_huge_body_fails_auth_without_decode():
    seen: list = []
    big = b'{"error": {"message": "' + b"X" * (CAP + OVER_TAIL) + b'"}}'

    def handle(req):
        seen.append(req)
        return httpx.Response(401, content=big, headers={"content-type": "application/json"})

    with pytest.raises(UpstreamAuthFailed):
        await byok.call_chat_completions(
            "sk-test-byok-0123456789abcdef",
            [{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=httpx.MockTransport(handle),
            base_url=BYOK_URL,
            upstream_model=BYOK_MODEL,
            timeout_seconds=30,
            response_model=BYOK_MODEL,
        )
    assert len(seen) == 1


# --- single-chunk pre-append boundary (#4379 post-#4547 follow-up) ---------
# Merged #4547 capped the TOTAL body before JSON decode, but the collector
# appended each incoming chunk BEFORE checking the cap, so one huge chunk
# could peak worker RAM beyond it. These tests pin pre-append semantics.


class _StubResponse:
    """Minimal duck-typed response: only .headers + .aiter_bytes()."""

    def __init__(self, chunks, headers=None):
        self._chunks = list(chunks)
        self.headers = dict(headers or {})

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_helper_single_huge_chunk_rejected_without_accumulator_peak():
    # One 2MiB decoded chunk (small finite fixture, no gigabyte alloc).
    # Before the fix, the whole chunk was copied into the accumulator first,
    # causing ~2MiB traced extra allocation. The fixed helper rejects that copy.
    big = b"Z" * (CAP + 1024 * 1024)
    stub = _StubResponse([big])
    resumed = tracemalloc.is_tracing()
    if resumed:
        tracemalloc.stop()
    tracemalloc.start()
    try:
        with pytest.raises(UpstreamResponseTooLarge):
            await plat._read_bounded_body(stub)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        if resumed:
            tracemalloc.start()
    assert peak < CAP


@pytest.mark.asyncio
async def test_helper_exact_cap_boundary_returned_verbatim():
    body = b"Q" * CAP
    got = await plat._read_bounded_body(_StubResponse([body]))
    assert got == body  # no truncation at the exact boundary


@pytest.mark.asyncio
async def test_helper_cap_plus_one_single_chunk_rejects():
    with pytest.raises(UpstreamResponseTooLarge):
        await plat._read_bounded_body(_StubResponse([b"Q" * (CAP + 1)]))


@pytest.mark.asyncio
async def test_helper_missing_content_length_enforced_on_bytes():
    stub = _StubResponse([b"Z" * (CAP // 2), b"Z" * (CAP // 2 + 1)])
    with pytest.raises(UpstreamResponseTooLarge):
        await plat._read_bounded_body(stub)


@pytest.mark.asyncio
async def test_helper_invalid_content_length_falls_back_to_bytes():
    body = b'{"ok": true}'
    got = await plat._read_bounded_body(
        _StubResponse([body], headers={"content-length": "not-a-number"})
    )
    assert got == body  # untrusted header never causes a false reject


@pytest.mark.asyncio
async def test_helper_lying_small_declaration_enforced_on_bytes():
    stub = _StubResponse(
        [b"Z" * (CAP + 8)], headers={"content-length": "10"}
    )
    with pytest.raises(UpstreamResponseTooLarge):
        await plat._read_bounded_body(stub)


@pytest.mark.asyncio
async def test_helper_tiny_chunk_sequence_roundtrips():
    body = b'{"ok": true}'
    got = await plat._read_bounded_body(
        _StubResponse([bytes([b]) for b in body])
    )
    assert got == body


@pytest.mark.asyncio
async def test_helper_timeout_propagates_not_swallowed():
    async def stalled():
        yield b"prefix"
        raise httpx.ReadTimeout("synthetic stall")

    class _Stalled:
        headers = {}
        aiter_bytes = lambda self: stalled()  # noqa: E731

    with pytest.raises(httpx.TimeoutException):
        await plat._read_bounded_body(_Stalled())


@pytest.mark.asyncio
async def test_generic_mid_body_timeout_maps_to_upstream_timeout(live_keyless_route):
    calls = []

    class _StallTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(1)

            async def gen():
                yield b'{"choices": ['
                raise httpx.ReadTimeout("synthetic stall")

            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=gen()
            )

    with pytest.raises(UpstreamTimeout):
        await plat.call_platform_chat_completions(
            model_id=MOCK_ID,
            upstream_model=MOCK_UPSTREAM,
            provider="Synthetic test-only gateway",
            platform_provider_id=MOCK_PROVIDER,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=_StallTransport(),
        )
    assert calls == [1]


@pytest.mark.asyncio
async def test_go_and_byok_single_huge_chunk_rejected(go_auth_stub):
    # Parity pin: both lanes reuse the shared collector, so one >8MiB chunk
    # raises the resource error on each path with a single attempt.
    big = b"Z" * (COMPLETED_CAP + 1)
    seen_go: list = []
    seen_byok: list = []

    def go_handle(req):
        seen_go.append(req)
        return httpx.Response(
            200, content=big, headers={"content-type": "application/json"}
        )

    def byok_handle(req):
        seen_byok.append(req)
        return httpx.Response(
            200, content=big, headers={"content-type": "application/json"}
        )

    with pytest.raises(UpstreamResponseTooLarge):
        await go.call_go_model(
            model_id=GO_MODEL,
            upstream_model=GO_UPSTREAM,
            messages=GO_TURNS,
            session_id=GO_SESSION,
            max_tokens=32,
            transport=httpx.MockTransport(go_handle),
        )
    with pytest.raises(UpstreamResponseTooLarge):
        await byok.call_chat_completions(
            "sk-test-byok-0123456789abcdef",
            [{"role": "user", "content": "hi"}],
            max_tokens=32,
            transport=httpx.MockTransport(byok_handle),
            base_url=BYOK_URL,
            upstream_model=BYOK_MODEL,
            timeout_seconds=30,
            response_model=BYOK_MODEL,
        )
    assert len(seen_go) == 1
    assert len(seen_byok) == 1


@pytest.mark.asyncio
async def test_runtime_config_max_response_bytes_is_not_wired(monkeypatch):
    # Policy truth (#4379): the legacy 1MiB config field is declared-only.
    # It does not change the error/SSE guard OR completed JSON memory budget;
    # widening it must not become a backdoor to unbounded Worker allocations.
    from app.pilot.b14_runtime_config import runtime_config

    assert plat.MAX_RESPONSE_BYTES == 1024 * 1024
    assert runtime_config.max_response_bytes == 1024 * 1024
    monkeypatch.setattr(runtime_config, "max_response_bytes", 64 * 1024 * 1024)
    with pytest.raises(UpstreamResponseTooLarge):
        await plat._read_bounded_body(_StubResponse([b"Z" * (CAP + 1)]))


# --- #4379 owner: valid completed JSON must not hit old artificial 1MiB -----
# Bounded JSON allocation still needs a finite Worker memory safety budget.


@pytest.mark.asyncio
async def test_generic_valid_2mib_json_must_not_hit_old_1mib_guard(live_keyless_route):
    answer = "G" * (2 * CAP)
    payload = json.dumps(_completed_doc(answer)).encode("utf-8")
    transport = ChunkCountingTransport(payload)
    got = await plat.call_platform_chat_completions(
        model_id=MOCK_ID, upstream_model=MOCK_UPSTREAM,
        provider="Synthetic test-only gateway", platform_provider_id=MOCK_PROVIDER,
        messages=[{"role": "user", "content": "long"}], transport=transport,
    )
    assert got["choices"][0]["message"]["content"] == answer
    assert got["_response_bytes"] == len(payload)
    assert transport.calls == 1 and transport.served_bytes == len(payload)


@pytest.mark.asyncio
async def test_go_valid_2mib_json_must_not_hit_old_1mib_guard(go_auth_stub):
    answer = "G" * (2 * CAP)
    payload = json.dumps(_go_doc(answer)).encode("utf-8")
    transport = ChunkCountingTransport(payload)
    got = await go.call_go_model(
        model_id=GO_MODEL, upstream_model=GO_UPSTREAM,
        messages=GO_TURNS, session_id=GO_SESSION,
        transport=transport,
    )
    assert got["choices"][0]["message"]["content"] == answer
    assert transport.calls == 1 and transport.served_bytes == len(payload)


@pytest.mark.asyncio
async def test_byok_valid_2mib_json_must_not_hit_old_1mib_guard():
    answer = "Y" * (2 * CAP)
    payload = json.dumps(_completed_doc(answer, model=BYOK_MODEL)).encode("utf-8")
    transport = ChunkCountingTransport(payload)
    got = await byok.call_chat_completions(
        "sk-test-byok-0123456789abcdef",
        [{"role": "user", "content": "long"}],
        transport=transport, base_url=BYOK_URL,
        upstream_model=BYOK_MODEL, timeout_seconds=30, response_model=BYOK_MODEL,
    )
    assert got["choices"][0]["message"]["content"] == answer
    assert transport.calls == 1 and transport.served_bytes == len(payload)



@pytest.mark.asyncio
async def test_generic_exact_8mib_completed_json_is_valid_verbatim(live_keyless_route):
    # Verify actual adapter+parser boundary, not just the byte collector.
    empty = json.dumps(_completed_doc("")).encode()
    answer = "Q" * (COMPLETED_CAP - len(empty))
    payload = json.dumps(_completed_doc(answer)).encode()
    assert len(payload) == COMPLETED_CAP
    transport = ChunkCountingTransport(payload)
    got = await plat.call_platform_chat_completions(
        model_id=MOCK_ID, upstream_model=MOCK_UPSTREAM,
        provider="Synthetic test-only gateway", platform_provider_id=MOCK_PROVIDER,
        messages=[{"role": "user", "content": "long"}], transport=transport,
    )
    assert got["choices"][0]["message"]["content"] == answer
    assert got["_response_bytes"] == COMPLETED_CAP and transport.calls == 1


@pytest.mark.asyncio
async def test_generic_completed_cap_plus_one_rejects_as_worker_resource(live_keyless_route):
    payload = json.dumps(_completed_doc("Q" * (COMPLETED_CAP + 1))).encode()
    transport = ChunkCountingTransport(payload)
    with pytest.raises(UpstreamResponseTooLarge) as exc:
        await plat.call_platform_chat_completions(
            model_id=MOCK_ID, upstream_model=MOCK_UPSTREAM,
            provider="Synthetic test-only gateway", platform_provider_id=MOCK_PROVIDER,
            messages=[{"role": "user", "content": "long"}], transport=transport,
        )
    assert exc.value.max_bytes == COMPLETED_CAP
    assert transport.calls == 1
    assert transport.served_bytes <= COMPLETED_CAP + CHUNK


@pytest.mark.asyncio
async def test_generic_error_body_still_enforces_separate_1mib_guard(live_keyless_route):
    # A vendor error is not a model's healthy answer, so it remains 1MiB.
    payload = b"X" * (CAP + 1)
    transport = ChunkCountingTransport(payload, status=500)
    with pytest.raises(UpstreamResponseTooLarge) as exc:
        await plat.call_platform_chat_completions(
            model_id=MOCK_ID, upstream_model=MOCK_UPSTREAM,
            provider="Synthetic test-only gateway", platform_provider_id=MOCK_PROVIDER,
            messages=[{"role": "user", "content": "long"}], transport=transport,
        )
    assert exc.value.max_bytes == CAP
    assert transport.calls == 1

def test_operator_summary_exposes_effective_completed_memory_guard():
    from app.pilot.b14_runtime_config import runtime_config
    summary = runtime_config.redacted_summary()
    assert "max_response_bytes_effect=no" in summary
    assert f"completed_json_memory_budget_bytes={COMPLETED_CAP}" in summary
    assert f"sse_frame_and_error_resource_bytes={CAP}" in summary
