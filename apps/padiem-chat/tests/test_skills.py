from __future__ import annotations

from types import MappingProxyType

import httpx
import pytest

from app.b14_client import B14Client, PADIEM_IDENTITY_INSTRUCTION
from app.config import Settings
from app.main import create_app
from app.model_policy import DEFAULT_B14_MODEL_ID
from app.task_modes import TASK_MODE_REGISTRY, get_task_mode, task_mode_public_metadata

USER_MESSAGES = [{"role": "user", "content": "테스트 질문"}]


def _success_payload():
    return {
        "choices": [{"message": {"role": "assistant", "content": "테스트 답변"}}],
        "business14": {
            "request_id": "b14req_skill",
            "route_mode": "manual",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "selected_provider": "Agnes AI",
        },
    }


def test_skill_registry_has_exact_initial_ids_and_is_immutable():
    assert isinstance(TASK_MODE_REGISTRY, MappingProxyType)
    # C1: 대표 결정 — plan·auto만 남는다.
    assert tuple(TASK_MODE_REGISTRY) == ("auto", "plan")
    assert len(TASK_MODE_REGISTRY) == 2
    assert len(set(TASK_MODE_REGISTRY)) == 2
    with pytest.raises(TypeError):
        TASK_MODE_REGISTRY["evil"] = get_task_mode("auto")  # type: ignore[index]


REMOVED_SKILL_IDS = ("explain", "write", "translate", "summarize", "code", "brainstorm")


@pytest.mark.parametrize("skill_id", REMOVED_SKILL_IDS)
def test_removed_task_modes_are_unknown_values(skill_id):
    # C1: 대표 결정으로 지운 6종은 조용한 auto 대체 없이 미지 값이다.
    with pytest.raises(ValueError, match="지원하지 않는 작업 모드"):
        get_task_mode(skill_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("skill_id", REMOVED_SKILL_IDS)
async def test_the_browser_request_refuses_each_removed_task_mode(skill_id):
    app = create_app(Settings(runtime_mode="mock"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/chat",
            json={"messages": USER_MESSAGES, "skill": skill_id},
        )
    assert response.status_code == 422
    assert response.json()["error"] == {"code": "stale_chat_client", "message": '\ud654\uba74\uc774 \uc624\ub798\ub418\uc5c8\uc2b5\ub2c8\ub2e4. \uc0c8\ub85c\uace0\uce68\uc774 \ud544\uc694\ud569\ub2c8\ub2e4.'}


def test_get_skill_defaults_to_auto_and_rejects_unknown():
    assert get_task_mode().id == "auto"
    assert get_task_mode(None).id == "auto"
    with pytest.raises(ValueError, match="지원하지 않는 작업 모드"):
        get_task_mode("not-a-skill")


def test_public_metadata_exposes_only_safe_fields():
    skill = get_task_mode("plan")
    public = task_mode_public_metadata(skill)
    assert public == {"id": "plan", "title": "계획 세우기"}
    assert "system_instruction" not in public
    assert skill.system_instruction is None
    assert skill.max_tokens is None


@pytest.mark.asyncio
async def test_skill_maps_routing_hints_without_response_shaping():
    seen = {}

    async def handler(request):
        seen["body"] = __import__("json").loads(request.content)
        return httpx.Response(200, json=_success_payload())

    skill = get_task_mode("plan")
    result = await B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        httpx.MockTransport(handler),
    ).complete(USER_MESSAGES, skill=skill)

    body = seen["body"]
    assert body["model"] == DEFAULT_B14_MODEL_ID
    assert "max_tokens" not in body
    # B4/B5: the scorer-era fields and the fallback knob no longer travel.
    for retired in ("task_type", "optimize_for", "allow_external_fallback", "max_attempts"):
        assert retired not in body["business14"]
    assert body["business14"]["required_capabilities"] == ["chat"]
    system_messages = [item for item in body["messages"] if item["role"] == "system"]
    assert len(system_messages) == 1
    assert PADIEM_IDENTITY_INSTRUCTION in system_messages[0]["content"]
    assert body["messages"][-1] == USER_MESSAGES[0]
    assert sum(1 for item in body["messages"] if item["role"] == "system") == 1
    assert result["skill"] == {"id": skill.id, "title": skill.title}
    assert result["route"]["model"] == DEFAULT_B14_MODEL_ID


@pytest.mark.asyncio
async def test_browser_cannot_override_skill_or_b14_routing_contract():
    app = create_app(Settings(runtime_mode="mock"))
    forbidden_payloads = [
        {"messages": USER_MESSAGES, "skill": {"id": "code"}},
        {"messages": USER_MESSAGES, "model": "provider/model"},
        {"messages": USER_MESSAGES, "provider": "provider-x"},
        {"messages": USER_MESSAGES, "business14": {"task_type": "coding"}},
        {"messages": USER_MESSAGES, "upstream_url": "https://evil.example"},
        {"messages": USER_MESSAGES, "b14_base_url": "https://evil.example"},
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
                "skill": "code",
            },
        )
    assert response.status_code == 422
    assert calls == 0
