"""#4317: the ordinary completed Chat path can use the owner-pinned Free roster.

The completed Chat path used to pin the upstream attempt count, so a
recoverable provider failure ended the request even though the owner-pinned
per-grade recovery chain was available. The pin was an artificial ceiling,
not a safety boundary.

B14 owns the whole recovery contract, and these tests pin the part of it the
Chat Worker is responsible for: it sends the verified product grade, it does
not pin the attempt count, and it does not ask for an arbitrary catalog
substitution. The B14-side walk is proved in
apps/korean-ai-platform/tests/test_4317_free_completed_tier_fallback.py.

No provider is contacted: the service binding is a local fake.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app import b14_client
from app.b14_client import B14Client
from app.config import Settings
from app.model_policy import DEFAULT_B14_MODEL_ID
from padiem_control_plane.product_tier_routes import FREE_PRIMARY_B14_MODEL_ID

USER_MESSAGES = [{"role": "user", "content": "안녕하세요"}]


class FakeServiceTransport:
    """Captures the exact B14 request the Chat Worker would send."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def post_json(self, url: str, payload: dict) -> tuple[int, bytes]:
        self.calls.append((url, payload))
        return 200, json.dumps(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "서비스 바인딩 응답입니다."}}
                ],
                "business14": {
                    "request_id": "b14req_4317",
                    "route_mode": "manual",
                    "selected_model": DEFAULT_B14_MODEL_ID,
                    "selected_provider": "Agnes AI",
                },
            }
        ).encode("utf-8")


def _client(service: FakeServiceTransport) -> B14Client:
    return B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.internal"),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        service_transport=service,
        require_service_binding=True,
    )


@pytest.mark.asyncio
async def test_the_completed_chat_path_leaves_the_attempt_count_to_b14():
    """The ordinary completed path does not pin the upstream attempt count."""
    service = FakeServiceTransport()
    client = _client(service)

    await client.complete(USER_MESSAGES)

    assert len(service.calls) == 1
    _url, payload = service.calls[0]
    business = payload["business14"]
    # B14 derives the attempt count from the candidates the declared grade
    # allows. A local pin would deny the owner-pinned recovery chain.
    assert "max_attempts" not in business
    # Arbitrary catalog substitution stays disabled.
    assert "allow_external_fallback" not in business
    # The verified product grade travels, so B14 resolves that grade's roster.
    assert business["product_tier"] == "free"


@pytest.mark.asyncio
async def test_the_completed_chat_path_sends_the_free_grade_primary():
    """The Free roster only applies to the Free grade's own primary route."""
    service = FakeServiceTransport()
    client = _client(service)

    await client.complete(USER_MESSAGES)

    _url, payload = service.calls[0]
    assert payload["model"] == FREE_PRIMARY_B14_MODEL_ID
    assert payload["model"] == DEFAULT_B14_MODEL_ID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "expected_tier"),
    [("free", "free"), ("low", "plus"), ("medium", "pro"), ("high", "max")],
)
async def test_the_verified_grade_travels_with_the_completed_request(
    monkeypatch, profile, expected_tier
):
    """The grade is the only thing that decides B14's roster, so it must travel."""
    monkeypatch.setattr(
        b14_client,
        "_resolve_b62_policy",
        lambda messages, **kwargs: SimpleNamespace(
            profile=profile, model_id=DEFAULT_B14_MODEL_ID, messages=messages
        ),
    )
    service = FakeServiceTransport()
    client = _client(service)

    await client.complete(USER_MESSAGES)

    _url, payload = service.calls[0]
    assert payload["business14"]["product_tier"] == expected_tier
    assert "max_attempts" not in payload["business14"]
    assert "allow_external_fallback" not in payload["business14"]


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def _sse_frame() -> bytes:
    payload = {
        "id": "b62_4317_stream",
        "object": "chat.completion.chunk",
        "model": DEFAULT_B14_MODEL_ID,
        "choices": [
            {"index": 0, "delta": {"content": "토큰"}, "finish_reason": None}
        ],
        "business14": {
            "request_id": "b14req_4317_stream",
            "route_mode": "manual",
            "selected_provider": "Google AI Studio",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "selected_upstream_model": DEFAULT_B14_MODEL_ID,
            "selected_route_id": f"platform:{DEFAULT_B14_MODEL_ID}",
            "fallback_used": False,
            "attempt_count": 1,
            "route_evidence_status": "live_streaming_router_preview",
        },
    }
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


def _assert_no_local_attempt_budget(business: dict) -> None:
    # B14 derives the attempt count from the candidates the declared grade
    # allows. A number here could only narrow that list.
    assert "max_attempts" not in business
    # Arbitrary catalog substitution stays disabled on every Chat surface.
    assert "allow_external_fallback" not in business


@pytest.mark.asyncio
async def test_every_chat_dispatch_surface_leaves_the_attempt_budget_to_b14(
    monkeypatch,
):
    """Completed, SSE and private stream must not disagree about the budget."""
    monkeypatch.setattr(
        b14_client,
        "_resolve_b62_policy",
        lambda messages, **kwargs: SimpleNamespace(
            profile="free",
            model_id=FREE_PRIMARY_B14_MODEL_ID,
            messages=messages,
        ),
    )
    service = FakeServiceTransport()
    completed_client = _client(service)
    await completed_client.complete(USER_MESSAGES)

    streamed: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        streamed.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_ChunkStream([_sse_frame(), b"data: [DONE]\n\n"]),
        )

    stream_client = B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.internal"),
        stream_transport=httpx.MockTransport(handler),
        require_service_binding=True,
    )
    auto_events = [
        event async for event in stream_client.stream_text_auto(USER_MESSAGES)
    ]
    preview_events = [
        event
        async for event in stream_client.stream_text_preview(
            USER_MESSAGES, model=FREE_PRIMARY_B14_MODEL_ID
        )
    ]

    assert auto_events[-1].done is True
    assert preview_events[-1].done is True
    assert len(service.calls) == 1
    assert len(streamed) == 2

    completed_business = service.calls[0][1]["business14"]
    auto_business = streamed[0]["business14"]
    preview_business = streamed[1]["business14"]
    for business in (completed_business, auto_business, preview_business):
        _assert_no_local_attempt_budget(business)

    # Wherever the surface resolves a verified grade, that grade must travel:
    # it is the only thing that decides B14's allowed candidate roster.
    assert completed_business["product_tier"] == "free"
    assert auto_business["product_tier"] == "free"
