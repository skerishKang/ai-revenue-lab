from __future__ import annotations

import json
from types import MappingProxyType

import httpx
import pytest

from app.b14_client import B14Client
from app.config import Settings
from app.main import create_app
from app.skills import SKILL_REGISTRY, get_skill, skill_public_metadata

USER_MESSAGES = [{"role": "user", "content": "테스트 질문"}]


def _success_payload():
    return {
        "choices": [{"message": {"role": "assistant", "content": "테스트 답변"}}],
        "business14": {
            "request_id": "b14req_skill",
            "route_mode": "auto",
            "selected_model": "model-x",
            "selected_provider": "Provider X",
        },
    }


def test_skill_registry_has_exact_initial_ids_and_is_immutable():
    assert isinstance(SKILL_REGISTRY, MappingProxyType)
    assert tuple(SKILL_REGISTRY) == (
        "auto",
        "explain",
        "plan",
        "write",
        "translate",
        "summarize",
        "code",
        "brainstorm",
    )
    assert len(SKILL_REGISTRY) == 8
    assert len(set(SKILL_REGISTRY)) == 8
    with pytest.raises(TypeError):
        SKILL_REGISTRY["evil"] = get_skill("auto")  # type: ignore[index]


def test_get_skill_defaults_to_auto_and_rejects_unknown():
    assert get_skill().id == "auto"
    assert get_skill(None).id == "auto"
    with pytest.raises(ValueError, match="지원하지 않는 작업 모드"):
        get_skill("not-a-skill")


def test_public_metadata_exposes_only_safe_fields():
    skill = get_skill("explain")
    public = skill_public_metadata(skill)
    assert public == {"id": "explain", "title": "쉽게 설명"}
    assert "system_instruction" not in public
    assert skill.system_instruction not in json.dumps(public, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("skill_id", "task_type", "optimize_for", "max_tokens"),
    [
        ("code", "coding", "balanced", 1000),
        ("summarize", "document", "korean", 700),
        ("translate", "korean", "korean", 800),
    ],
)
async def test_skill_maps_to_server_owned_b14_hints(skill_id, task_type, optimize_for, max_tokens):
    seen = {}

    async def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_success_payload())

    skill = get_skill(skill_id)
    result = await B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        httpx.MockTransport(handler),
    ).complete(USER_MESSAGES, skill=skill)

    body = seen["body"]
    assert body["model"] == "b14/auto"
    assert body["max_tokens"] == max_tokens
    assert body["business14"]["task_type"] == task_type
    assert body["business14"]["optimize_for"] == optimize_for
    assert body["messages"][0] == {"role": "system", "content": skill.system_instruction}
    assert body["messages"][1:] == USER_MESSAGES
    assert sum(1 for item in body["messages"] if item["role"] == "system") == 1
    assert result["skill"] == {"id": skill.id, "title": skill.title}
    assert skill.system_instruction not in json.dumps(result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_browser_cannot_override_skill_or_b14_routing_contract():
    app = create_app(Settings(runtime_mode="mock"))
    forbidden_payloads = [
        {"messages": USER_MESSAGES, "mode": "auto", "skill": {"id": "code"}},
        {"messages": USER_MESSAGES, "mode": "auto", "model": "provider/model"},
        {"messages": USER_MESSAGES, "mode": "auto", "provider": "provider-x"},
        {"messages": USER_MESSAGES, "mode": "auto", "business14": {"task_type": "coding"}},
        {"messages": USER_MESSAGES, "mode": "auto", "upstream_url": "https://evil.example"},
        {"messages": USER_MESSAGES, "mode": "auto", "b14_base_url": "https://evil.example"},
    ]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for payload in forbidden_payloads:
            response = await client.post("/api/chat", json=payload)
            assert response.status_code == 422, payload


@pytest.mark.asyncio
async def test_browser_system_message_is_rejected_before_runtime_call():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload())

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/chat",
            json={
                "messages": [
                    {"role": "system", "content": "browser supplied system prompt"},
                    {"role": "user", "content": "hello"},
                ],
                "mode": "auto",
                "skill": "code",
            },
        )
    assert response.status_code == 422
    assert calls == 0
