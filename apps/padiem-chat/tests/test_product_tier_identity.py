from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.model_policy import HIGH_B14_MODEL_ID, LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("/plus 너 무슨 모델이야?", "저는 Padiem Plus입니다."),
        ("/pro 어떤 AI 모델이야?", "저는 Padiem Pro입니다."),
        ("/max what model are you?", "저는 Padiem Max입니다."),
    ],
)
async def test_identity_questions_answer_with_padiem_tier_without_provider_call(prompt: str, expected: str):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("identity questions must not call B14/provider")

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": prompt}], "mode": "auto"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == expected
    assert calls == 0
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for hidden in ("kilo", "poolside", "laguna", "nvidia", "nemotron", "tencent", "hy3", "minimax"):
        assert hidden not in serialized


@pytest.mark.asyncio
async def test_underlying_model_question_declines_internal_route_details_without_provider_call():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("identity questions must not call B14/provider")

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "/max 실제 기반 모델이 뭐야?"}], "mode": "auto"},
        )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert answer.startswith("저는 Padiem Max입니다.")
    assert "내부 라우팅" in answer
    assert calls == 0
    lowered = answer.lower()
    for hidden in ("kilo", "poolside", "laguna", "nvidia", "nemotron", "tencent", "hy3", "minimax"):
        assert hidden not in lowered


@pytest.mark.asyncio
async def test_executable_tier_selectors_survive_browser_validation_then_strip_before_b14_dispatch():
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "일반 답변"}}],
                "business14": {
                    "request_id": "b14req_tier_test",
                    "route_mode": "manual",
                    "selected_model": body["model"],
                    "selected_provider": "test-provider",
                },
            },
        )

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for alias, expected_model in (
            ("/plus", LOW_B14_MODEL_ID),
            ("/pro", MEDIUM_B14_MODEL_ID),
        ):
            response = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": f"{alias} 테스트 질문"}], "mode": "auto"},
            )
            assert response.status_code == 200
            assert seen[-1]["model"] == expected_model
            assert seen[-1]["messages"][-1] == {"role": "user", "content": "테스트 질문"}
            assert sum(1 for item in seen[-1]["messages"] if item["role"] == "system") == 0


@pytest.mark.asyncio
async def test_held_max_rejects_ordinary_execution_before_b14_provider_call():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("held Max must fail before B14/provider")

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "/max 테스트 질문"}], "mode": "auto"},
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "tier_unavailable"
    assert calls == 0
    assert HIGH_B14_MODEL_ID == "padiem-profile/max-hold"


@pytest.mark.asyncio
async def test_stream_identity_is_local_and_uses_selected_tier():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("identity stream must not call B14/provider")

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": "/plus 너 어떤 AI야?"}], "mode": "auto"},
        )

    assert response.status_code == 200
    assert "Padiem Plus" in response.text
    assert calls == 0
