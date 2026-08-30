from __future__ import annotations

import hashlib
import json
import secrets
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test_candidate"))

from candidate_app import (  # noqa: E402
    CANONICAL_HOST,
    POOL_SIDE_MODEL,
    TEST_GUARD_DIGEST_BINDING,
    TEST_GUARD_HEADER,
    create_app,
    guard_matches,
    request_guard_matches,
)

BASE_URL = "https://padiem-chat.charliekant.workers.dev"


class CountingSecret:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self) -> str:
        self.calls += 1
        return "test-only-mock-credential"


def make_guard() -> tuple[str, str]:
    raw = secrets.token_hex(32)
    return raw, hashlib.sha256(raw.encode("ascii")).hexdigest()


def test_guard_requires_ephemeral_256_bit_hex_token() -> None:
    raw, digest = make_guard()
    assert len(raw) == 64
    assert guard_matches(raw, digest)
    assert request_guard_matches(CANONICAL_HOST, raw, digest)
    assert not request_guard_matches("preview.example", raw, digest)
    assert not guard_matches(None, digest)
    assert not guard_matches("not-a-token", digest)
    assert not guard_matches("g" * 64, digest)
    assert not guard_matches(raw, "0" * 63)


@pytest.mark.asyncio
async def test_guard_rejection_precedes_secret_access_and_health_is_redacted() -> None:
    secret = CountingSecret()
    raw, digest = make_guard()
    app = create_app(secret, digest)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        for headers in ({}, {TEST_GUARD_HEADER: "wrong"}, {TEST_GUARD_HEADER: "g" * 64}):
            response = await client.get("/health", headers=headers)
            assert response.status_code == 403

        wrong_host = await client.get(
            "/health",
            headers={TEST_GUARD_HEADER: raw, "Host": "preview.example"},
        )
        assert wrong_host.status_code == 403
        assert secret.calls == 0

        response = await client.get("/health", headers={TEST_GUARD_HEADER: raw})
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "app": "padiem-chat", "runtime": "test_direct"}
        assert TEST_GUARD_DIGEST_BINDING not in response.text
        assert "task" not in response.text.lower()
        assert "poolside" not in response.text.lower()
        assert "model" not in response.text.lower()
        assert "route" not in response.text.lower()
        assert digest != raw


@pytest.mark.asyncio
async def test_correct_guard_reaches_only_mocked_provider_path() -> None:
    raw, digest = make_guard()
    secret = CountingSecret()
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "mocked answer"}}]})

    app = create_app(secret, digest, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        response = await client.post(
            "/api/chat",
            headers={TEST_GUARD_HEADER: raw},
            json={"messages": [{"role": "user", "content": "테스트"}]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "mocked answer",
        "runtime": "test_direct",
        "skill": {"id": "auto", "title": "자동 추천"},
    }
    assert secret.calls == 1
    assert seen["authorization"] == "Bearer test-only-mock-credential"
    assert seen["body"]["model"] == POOL_SIDE_MODEL
    assert digest != raw


@pytest.mark.asyncio
async def test_stream_requires_terminal_done_or_finish_reason() -> None:
    raw, digest = make_guard()
    secret = CountingSecret()

    async def incomplete(_request: httpx.Request) -> httpx.Response:
        body = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    app = create_app(secret, digest, transport=httpx.MockTransport(incomplete))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        response = await client.post(
            "/api/chat/stream",
            headers={TEST_GUARD_HEADER: raw},
            json={"messages": [{"role": "user", "content": "테스트"}]},
        )

    assert response.status_code == 200
    assert "event: delta" in response.text
    assert '"code": "incomplete_upstream_stream"' in response.text
    assert "event: done" not in response.text


@pytest.mark.asyncio
async def test_document_path_preserves_only_bounded_text_context() -> None:
    raw, digest = make_guard()
    secret = CountingSecret()
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "문서 답변"}}]})

    app = create_app(secret, digest, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        response = await client.post(
            "/api/chat",
            headers={TEST_GUARD_HEADER: raw},
            json={
                "messages": [{"role": "user", "content": "문서의 고유 사실을 알려줘."}],
                "attachments": [
                    {
                        "type": "document",
                        "name": "fact.txt",
                        "media_type": "text/plain",
                        "text": "고유 사실: 테스트용 파란 나무는 17미터입니다.",
                    }
                ],
            },
        )

    assert response.status_code == 200
    assert response.json()["runtime"] == "test_direct"
    assert "route" not in response.text.lower()
    assert "provider" not in response.text.lower()
    assert "model" not in response.text.lower()
    provider_messages = seen["body"]["messages"]
    assert "고유 사실: 테스트용 파란 나무는 17미터입니다." in provider_messages[0]["content"]


@pytest.mark.asyncio
async def test_stream_done_marker_emits_public_done_event() -> None:
    raw, digest = make_guard()
    secret = CountingSecret()
    sse = (
        'data: {"choices":[{"delta":{"content":"완료 답변"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))

    app = create_app(secret, digest, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        response = await client.post(
            "/api/chat/stream",
            headers={TEST_GUARD_HEADER: raw},
            json={"messages": [{"role": "user", "content": "스트림 완료 테스트"}]},
        )

    assert response.status_code == 200
    assert "event: delta" in response.text
    assert '"done":true' in response.text
    assert "event: error" not in response.text
