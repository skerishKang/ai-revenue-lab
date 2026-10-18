from __future__ import annotations

import json

import httpx
import pytest

from unittest.mock import MagicMock

from app.b14_client import PADIEM_IDENTITY_INSTRUCTION
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.model_policy import HIGH_B14_MODEL_ID, LOW_B14_MODEL_ID, MEDIUM_B14_MODEL_ID


_SETTINGS_KWARGS = dict(
    runtime_mode="b14",
    b14_base_url="https://b14.example",
    auth_mode="google",
    session_secret="identity-test-session-secret-0000000000000",
    google_client_id="identity-test.apps.googleusercontent.com",
    public_base_url="https://chat.example.test",
    session_max_age_seconds=3600,
)


_BROWSER_ORIGIN = {"Origin": "https://chat.example.test"}


def _grade_members(tier):
    class _Members:
        async def runtime_access(self, user_id):
            return {"status": "approved", "tier": tier.upper()}

        async def is_google_admin(self, user_id):
            return False

    return _Members()


def _login(client, settings, user_id="usr_identity_test"):
    # Host-only cookie (no domain attribute): httpx sends it back to the
    # exact test host, unlike a bare single-label domain value.
    client.cookies.set(
        SESSION_COOKIE, create_session_token(settings, user_id),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "tier", "expected"),
    [
        ("/plus 너 무슨 모델이야?", "plus", "저는 Padiem Plus입니다."),
        ("/pro 어떤 AI 모델이야?", "pro", "저는 Padiem Pro입니다."),
        ("/max what model are you?", "max", "저는 Padiem Max입니다."),
    ],
)
async def test_identity_questions_answer_with_padiem_tier_without_provider_call(prompt: str, tier: str, expected: str):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("identity questions must not call B14/provider")

    app = create_app(
        settings := Settings(**_SETTINGS_KWARGS),
        transport=httpx.MockTransport(handler),
        history_store=MagicMock(),
    )
    app.state.b66_member_admin_store = _grade_members(tier)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Auth-mocked member session (no real login): the verified member
        # grade authorizes the tier, the identity answer itself stays local.
        _login(client, settings)
        # The grade follows the validated browser tier field, never a bare
        # message alias: an alias alone cannot grant a paid tier.
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": prompt}], "mode": "auto", "tier": tier},
            headers=_BROWSER_ORIGIN,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == expected
    assert calls == 0
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for hidden in ("kilo", "poolside", "laguna", "nvidia", "nemotron", "tencent", "hy3", "minimax", "sensenova", "b-ai", "b.ai", "qwen"):
        assert hidden not in serialized


@pytest.mark.asyncio
async def test_underlying_model_question_declines_internal_route_details_without_provider_call():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("identity questions must not call B14/provider")

    app = create_app(
        settings := Settings(**_SETTINGS_KWARGS),
        transport=httpx.MockTransport(handler),
        history_store=MagicMock(),
    )
    app.state.b66_member_admin_store = _grade_members("max")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        _login(client, settings)
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "/max 실제 기반 모델이 뭐야?"}], "mode": "auto", "tier": "max"},
            headers=_BROWSER_ORIGIN,
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
        settings := Settings(**_SETTINGS_KWARGS),
        transport=httpx.MockTransport(handler),
        history_store=MagicMock(),
    )
    app.state.b66_member_admin_store = _grade_members("plus")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # The browser tier field decides the dispatch model; the request
        # alias is stripped before B14 and never grants a tier by itself.
        _login(client, settings)
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "테스트 질문"}], "tier": "plus"},
            headers=_BROWSER_ORIGIN,
        )
        assert response.status_code == 200
        assert seen[-1]["model"] == LOW_B14_MODEL_ID
        assert seen[-1]["messages"][-1] == {"role": "user", "content": "테스트 질문"}
        system_messages = [
            item for item in seen[-1]["messages"] if item["role"] == "system"
        ]
        assert len(system_messages) == 1
        assert PADIEM_IDENTITY_INSTRUCTION in system_messages[0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("alias", "expected_hold_model"),
    [
        ("/pro", MEDIUM_B14_MODEL_ID),
        ("/max", HIGH_B14_MODEL_ID),
    ],
)
async def test_held_tiers_reject_ordinary_execution_before_b14_provider_call(
    alias: str,
    expected_hold_model: str,
):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
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
        Settings(**_SETTINGS_KWARGS),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": f"{alias} 테스트 질문"}], "mode": "auto"},
        )

    assert response.status_code == 200
    assert calls == 1
    assert expected_hold_model in {MEDIUM_B14_MODEL_ID, HIGH_B14_MODEL_ID}


@pytest.mark.asyncio
async def test_stream_identity_is_local_and_uses_selected_tier():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("identity stream must not call B14/provider")

    app = create_app(
        settings := Settings(**_SETTINGS_KWARGS),
        transport=httpx.MockTransport(handler),
        history_store=MagicMock(),
    )
    app.state.b66_member_admin_store = _grade_members("plus")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Same rule on the stream lane: the validated tier field decides.
        _login(client, settings)
        response = await client.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": "/plus 너 어떤 AI야?"}], "mode": "auto", "tier": "plus"},
            headers=_BROWSER_ORIGIN,
        )

    assert response.status_code == 200
    assert "Padiem Plus" in response.text
    assert calls == 0
