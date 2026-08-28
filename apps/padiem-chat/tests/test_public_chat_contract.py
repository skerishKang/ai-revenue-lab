from __future__ import annotations

import json

import httpx
import pytest

from padiem_ai_core import B14StreamEvent

from app.config import Settings
from app.main import create_app
from app.public_chat import public_chat_result

MODEL_SENTINEL = "MODEL_PRIVATE_SENTINEL_9f3a"
PROVIDER_SENTINEL = "PROVIDER_PRIVATE_SENTINEL_7c2b"
REQUEST_SENTINEL = "REQUEST_PRIVATE_SENTINEL_4d1e"


def _assert_private_identity_absent(raw: bytes | str) -> None:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    assert MODEL_SENTINEL not in text
    assert PROVIDER_SENTINEL not in text
    assert REQUEST_SENTINEL not in text


def test_public_projection_is_allowlisted_and_recursively_strips_identity() -> None:
    internal = {
        "answer": "공개 답변",
        "runtime": "b14",
        "request_id": REQUEST_SENTINEL,
        "route": {
            "mode": "manual",
            "model": MODEL_SENTINEL,
            "provider": PROVIDER_SENTINEL,
        },
        "skill": {"id": "auto", "title": "자동 추천"},
        "evidence": [
            {
                "id": "source-1",
                "title": "공개 출처",
                "url": "https://example.com/source",
                "snippet": "공개 근거",
                "provider": PROVIDER_SENTINEL,
                "source_type": "web",
            }
        ],
        "research": {
            "status": "complete",
            "selected_model": MODEL_SENTINEL,
            "selected_provider": PROVIDER_SENTINEL,
        },
        "internal_debug": {"model_id": MODEL_SENTINEL},
    }

    public = public_chat_result(internal)
    raw = json.dumps(public, ensure_ascii=False)

    assert public["answer"] == "공개 답변"
    assert public["evidence"][0]["title"] == "공개 출처"
    assert public["research"] == {"status": "complete"}
    assert "route" not in public
    assert "request_id" not in public
    assert "internal_debug" not in public
    assert "provider" not in public["evidence"][0]
    _assert_private_identity_absent(raw)


@pytest.mark.asyncio
async def test_completed_browser_json_never_contains_internal_identity_bytes() -> None:
    class SentinelClient:
        async def complete(self, *args, **kwargs):
            return {
                "answer": "브라우저 공개 답변",
                "runtime": "b14",
                "request_id": REQUEST_SENTINEL,
                "route": {
                    "mode": "manual",
                    "model": MODEL_SENTINEL,
                    "provider": PROVIDER_SENTINEL,
                },
                "skill": {"id": "auto", "title": "자동 추천"},
            }

    app = create_app(Settings(runtime_mode="mock"))
    app.state.b14_client = SentinelClient()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "질문"}], "mode": "auto"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "브라우저 공개 답변",
        "runtime": "b14",
        "skill": {"id": "auto", "title": "자동 추천"},
    }
    _assert_private_identity_absent(response.content)


@pytest.mark.asyncio
async def test_browser_sse_never_serializes_internal_stream_model_identity() -> None:
    class SentinelStreamClient:
        async def stream_text_auto(self, *args, **kwargs):
            yield B14StreamEvent(
                response_id=REQUEST_SENTINEL,
                model=f"{MODEL_SENTINEL}:{PROVIDER_SENTINEL}",
                delta_content="첫 조각",
            )
            yield B14StreamEvent(
                response_id=REQUEST_SENTINEL,
                model=f"{MODEL_SENTINEL}:{PROVIDER_SENTINEL}",
                delta_content="둘째 조각",
            )
            yield B14StreamEvent(
                response_id=REQUEST_SENTINEL,
                model=f"{MODEL_SENTINEL}:{PROVIDER_SENTINEL}",
                done=True,
            )

    app = create_app(Settings(runtime_mode="mock"))
    app.state.b14_client = SentinelStreamClient()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": "질문"}], "mode": "auto"},
        )

    assert response.status_code == 200
    assert "event: delta" in response.text
    assert "event: done" in response.text
    assert "첫 조각" in response.text
    assert "둘째 조각" in response.text
    _assert_private_identity_absent(response.content)
