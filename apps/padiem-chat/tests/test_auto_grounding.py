from __future__ import annotations

import json

import httpx
import pytest

from app.auto_grounding import AutoGroundingService
from app.config import Settings
from app.evidence import Evidence
from app.grounding import GroundedChatService
from app.main import create_app
from app.model_policy import DEFAULT_B14_MODEL_ID


CURRENT = [{"role": "user", "content": "오늘 공개된 AI 정책을 찾아서 알려줘"}]
STABLE = [{"role": "user", "content": "중력의 원리를 쉽게 설명해줘"}]


def completion_payload(answer: str = "근거 [1]에 따르면 확인된 내용입니다.") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": answer}}],
        "business14": {
            "request_id": "b14req_auto_grounded",
            "route_mode": "manual",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "selected_provider": "Poolside",
        },
    }


class RecordingProvider:
    def __init__(self):
        self.search_calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 5):
        self.search_calls.append((query, limit))
        return [
            Evidence(
                id=f"auto_{index}",
                title=f"Verified source {index}",
                url=f"https://example.com/source/{index}",
                snippet=f"Verified current fact {index}",
                retrieved_at="2026-09-01T00:00:00Z",
                provider="test",
                source_type="search",
            )
            for index in range(1, limit + 1)
        ]

    async def fetch(self, url: str):
        raise AssertionError("automatic simple search must not fetch pages")


def install_provider(app, provider) -> None:
    app.state.web_provider = provider
    app.state.grounded_chat = GroundedChatService(app.state.b14_client, provider)
    app.state.auto_grounding = AutoGroundingService(provider)


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


def stream_frame(text: str) -> bytes:
    payload = {
        "id": "stream_auto_grounded",
        "object": "chat.completion.chunk",
        "model": DEFAULT_B14_MODEL_ID,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        "business14": {
            "request_id": "b14req_auto_grounded",
            "route_mode": "manual",
            "selected_provider": "Poolside",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "selected_upstream_model": "poolside/laguna-s-2.1",
            "fallback_used": False,
            "attempt_count": 1,
        },
    }
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"


def parse_public_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in text.replace("\r\n", "\n").split("\n\n"):
        if not frame.strip():
            continue
        event = "message"
        data = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
        if data is not None:
            events.append((event, json.loads(data)))
    return events


@pytest.mark.asyncio
async def test_current_question_auto_searches_once_and_returns_grounded_envelope() -> None:
    seen: list[dict] = []

    async def b14_handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=completion_payload())

    app = create_app(
        Settings(
            runtime_mode="b14",
            b14_base_url="https://b14.example",
            web_provider="mock",
        ),
        transport=httpx.MockTransport(b14_handler),
    )
    provider = RecordingProvider()
    install_provider(app, provider)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat", json={"messages": CURRENT, "mode": "auto"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer_status"] == "answered_with_evidence"
    assert body["tool"] == {"id": "web_search", "title": "웹 검색"}
    assert len(body["evidence"]) == 5
    assert "provider" not in body["evidence"][0]
    assert provider.search_calls == [(CURRENT[0]["content"], 5)]
    assert len(seen) == 1
    system = seen[0]["messages"][0]["content"]
    assert "웹 근거 사용 규칙" in system
    assert "근거에 없는 사실을 확인된 것처럼 단정하지 마세요" in system


@pytest.mark.asyncio
async def test_stable_concept_does_not_over_search() -> None:
    seen: list[dict] = []

    async def b14_handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=completion_payload("중력은 질량 사이의 상호작용입니다."))

    app = create_app(
        Settings(
            runtime_mode="b14",
            b14_base_url="https://b14.example",
            web_provider="mock",
        ),
        transport=httpx.MockTransport(b14_handler),
    )
    provider = RecordingProvider()
    install_provider(app, provider)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat", json={"messages": STABLE, "mode": "auto", "skill": "explain"})

    assert response.status_code == 200
    body = response.json()
    assert "answer_status" not in body
    assert "evidence" not in body
    assert provider.search_calls == []
    assert len(seen) == 1
    assert "웹 근거 사용 규칙" not in seen[0]["messages"][0]["content"]
    assert "확인되지 않은 사실" in seen[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_required_search_with_web_off_fails_before_laguna() -> None:
    b14_calls = 0

    async def b14_handler(request: httpx.Request) -> httpx.Response:
        nonlocal b14_calls
        b14_calls += 1
        return httpx.Response(200, json=completion_payload())

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example", web_provider="off"),
        transport=httpx.MockTransport(b14_handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat", json={"messages": CURRENT, "mode": "auto"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "web_tools_off"
    assert b14_calls == 0


@pytest.mark.asyncio
async def test_current_question_streams_after_search_and_done_exposes_safe_evidence() -> None:
    seen: list[dict] = []

    async def b14_handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([stream_frame("확인된 "), stream_frame("내용 [1]"), b"data: [DONE]\n\n"]),
        )

    app = create_app(
        Settings(
            runtime_mode="b14",
            b14_base_url="https://b14.example",
            web_provider="mock",
        ),
        transport=httpx.MockTransport(b14_handler),
    )
    provider = RecordingProvider()
    install_provider(app, provider)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat/stream", json={"messages": CURRENT, "mode": "auto"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_public_sse(response.text)
    deltas = [payload["delta"] for event, payload in events if event == "delta"]
    assert deltas == ["확인된 ", "내용 [1]"]
    done = [payload for event, payload in events if event == "done"][-1]
    assert done["done"] is True
    assert done["answer_status"] == "answered_with_evidence"
    assert done["tool"] == {"id": "web_search", "title": "웹 검색"}
    assert len(done["evidence"]) == 5
    assert "provider" not in done["evidence"][0]
    assert provider.search_calls == [(CURRENT[0]["content"], 5)]
    assert len(seen) == 1
    assert seen[0]["model"] == DEFAULT_B14_MODEL_ID
    assert seen[0]["business14"]["allow_external_fallback"] is False
    assert seen[0]["business14"]["max_attempts"] == 1
    assert "웹 근거 사용 규칙" in seen[0]["messages"][0]["content"]


class EmptyProvider:
    async def search(self, query: str, limit: int = 5):
        return []

    async def fetch(self, url: str):
        raise AssertionError("fetch must not run")


@pytest.mark.asyncio
async def test_stream_required_search_with_no_evidence_never_calls_laguna() -> None:
    b14_calls = 0

    async def b14_handler(request: httpx.Request) -> httpx.Response:
        nonlocal b14_calls
        b14_calls += 1
        return httpx.Response(500)

    app = create_app(
        Settings(
            runtime_mode="b14",
            b14_base_url="https://b14.example",
            web_provider="mock",
        ),
        transport=httpx.MockTransport(b14_handler),
    )
    provider = EmptyProvider()
    install_provider(app, provider)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat/stream", json={"messages": CURRENT, "mode": "auto"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_evidence"
    assert b14_calls == 0
