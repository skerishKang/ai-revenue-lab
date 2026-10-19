"""#5121 PADIEM Custom (BYOK): Claw and B66 direct execution.

These tests reuse the merged #5131 contract: one owner-scoped sealed key and
one explicit provider selection execute directly. The B14 client, router,
registry, default/fallback policy and platform usage reservation are never
touched on the BYOK path; the existing managed lanes stay unchanged when the
request carries no ``custom`` selection.

All provider traffic is a local mock transport. No live/paid model is called.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.b66_quote_conversation import B66QuoteConversationProjection
from app.byok_client import CustomProviderClient
from app.byok_credentials import D1CustomProviderCredentialStore
from app.main import create_app
from test_5121_byok_chat_direct import (
    CUSTOM_KEY,
    CUSTOM_KEY_SECRET,
    MODEL_ID,
    ORIGIN,
    OWNER,
    PROVIDER_ID,
    SESSION_SECRET,
    B14Bomb,
    FakeAuthenticatedCipher,
    MemoryHistoryStore,
    ProviderRecorder,
    SQLiteD1,
    request,
    settings,
    sse_events,
)

B66_MODEL = "google/gemini-3.5-flash-lite"
SAVED_ID = "b66skill_" + "c" * 32


class AdapterBomb:
    """Any P01 Engine dispatch on the BYOK path is a contract violation."""

    calls = 0

    def __getattr__(self, name):
        type(self).calls += 1
        raise AssertionError(f"P01 adapter touched on BYOK_DIRECT: {name}")


class QuoteStore:
    def __init__(self):
        self.calls = []

    async def get_skill(self, *, user_id, workspace_id, saved_skill_id):
        self.calls.append((user_id, workspace_id, saved_skill_id))
        if user_id != OWNER or saved_skill_id != SAVED_ID:
            return None
        return {
            "saved_skill_id": SAVED_ID,
            "workspace_id": workspace_id,
            "skill_id": "saved-skill-1",
            "skill_name": "우리 견적서",
            "skill_fingerprint": "d" * 64,
            "skill_version": 1,
            "status": "approved",
            "skill": {
                "schemaVersion": 1,
                "id": "saved-skill-1",
                "name": "우리 견적서",
                "fixedDefaults": {"taxMode": "EXCLUSIVE"},
                "variableSchema": {
                    "recipient": True,
                    "quoteNo": True,
                    "issueDate": True,
                    "items": True,
                    "memo": True,
                    "taxMode": True,
                },
            },
        }


class RecordingInterpreter:
    def __init__(self):
        self.calls = []

    async def interpret(self, *, message, skill, model_id=None, **kwargs):
        self.calls.append((message, model_id, kwargs))
        return B66QuoteConversationProjection(
            recipient={
                "company": "ABC건설",
                "person": None,
                "address": None,
                "email": None,
            },
            quote_no=None,
            issue_date=None,
            items=({"name": "배관", "qty": 20, "unitPrice": 30000},),
            memo=None,
            tax_mode=None,
            missing=(),
            result_origin=kwargs.get("result_origin") or "registered_model_completion",
        )


def build_app(
    *,
    recorder=None,
    interpreter=None,
    quote_store=None,
    adapter=None,
    d1=None,
):
    history = MemoryHistoryStore()
    history.add_user(OWNER)
    d1 = d1 or SQLiteD1()
    credential_store = D1CustomProviderCredentialStore(
        d1,
        key_secret=CUSTOM_KEY_SECRET,
        session_secret=SESSION_SECRET,
        cipher=FakeAuthenticatedCipher(),
    )
    recorder = recorder or ProviderRecorder()
    app = create_app(
        settings(),
        history_store=history,
        b66_saved_quote_skill_store=quote_store,
        b66_quote_interpreter=interpreter,
        claw_p01_adapter=adapter,
        custom_credential_store=credential_store,
        custom_provider_client=CustomProviderClient(transport=recorder.transport),
    )
    app.state.b14_client = B14Bomb()
    app.state.b14_catalog_source = B14Bomb()
    app.state.b66_quote_model_resolver = B14Bomb()
    app.state.usage_gate_enforced = False
    B14Bomb.touches = 0
    AdapterBomb.calls = 0
    return app, history, credential_store, recorder


def custom() -> dict[str, str]:
    return {"provider": PROVIDER_ID, "model": MODEL_ID}


def provider_json(payload: dict) -> ProviderRecorder:
    content = json.dumps(payload, ensure_ascii=False)
    return ProviderRecorder(
        lambda _request: httpx.Response(
            200, json={"model": "beam-free", "choices": [{"message": {"content": content}}]},
        )
    )


@pytest.mark.asyncio
async def test_session_secret_rotation_keeps_dedicated_key_readable():
    """Rotating the session secret must not affect BYOK rows.

    The sealed key is derived from the dedicated Custom key secret, so a new
    session secret still opens the same row. Legacy v1 rows and their explicit
    compatibility ring are verified in ``test_5121_byok_key_separation.py``.
    """
    d1 = SQLiteD1()
    before = D1CustomProviderCredentialStore(
        d1,
        key_secret=CUSTOM_KEY_SECRET,
        session_secret=SESSION_SECRET,
        cipher=FakeAuthenticatedCipher(),
    )
    await before.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)
    assert await before.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY

    rotated = D1CustomProviderCredentialStore(
        d1,
        key_secret=CUSTOM_KEY_SECRET,
        session_secret=SESSION_SECRET + "-rotated",
        cipher=FakeAuthenticatedCipher(),
    )
    assert await rotated.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY
    assert d1.sealed_values()


# ---------------------------------------------------------------------------
# Claw
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claw_custom_calls_provider_directly_without_engine_or_b14():
    app, history, credential_store, recorder = build_app(adapter=AdapterBomb())
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)

    response = await request(
        app, "POST", "/api/claw/general", uid=OWNER,
        json_body={
            "messages": [{"role": "user", "content": "안녕하세요"}],
            "custom": custom(),
        },
    )
    assert response.status_code == 200, response.text
    events = sse_events(response.text)
    assert [name for name, _ in events] == ["delta", "done"]
    assert events[0][1] == {"delta": "custom 답변"}
    conversation_id = events[1][1]["conversation_id"]
    assert conversation_id.startswith("chat_")
    assert CUSTOM_KEY not in response.text
    assert B14Bomb.touches == 0
    assert AdapterBomb.calls == 0

    assert len(recorder.requests) == 1
    wire = recorder.requests[0]
    assert str(wire.url) == "https://opencode.ai/inference/go/v1/chat/completions"
    assert wire.headers["authorization"] == "Bearer " + CUSTOM_KEY
    sent = json.loads(wire.content)
    assert sent["model"] == "beam-free"
    assert sent["messages"][1] == {"role": "user", "content": "안녕하세요"}

    saved = history.conversations[conversation_id]
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]
    assert saved["messages"][1]["content"] == "custom 답변"


@pytest.mark.asyncio
async def test_claw_custom_rejects_conflicts_tools_and_missing_key():
    app, _, _, recorder = build_app(adapter=AdapterBomb())

    conflict = await request(
        app, "POST", "/api/claw/general", uid=OWNER,
        json_body={
            "messages": [{"role": "user", "content": "안녕"}],
            "tier": "plus",
            "custom": custom(),
        },
    )
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "custom_selection_conflict"

    tool = await request(
        app, "POST", "/api/claw/general", uid=OWNER,
        json_body={
            "messages": [{"role": "user", "content": "내 PC 파일 목록 보여줘"}],
            "custom": custom(),
        },
    )
    assert tool.status_code == 422
    assert tool.json()["error"]["code"] == "custom_tool_unsupported"

    missing = await request(
        app, "POST", "/api/claw/general", uid=OWNER,
        json_body={
            "messages": [{"role": "user", "content": "안녕"}],
            "custom": custom(),
        },
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "custom_credential_required"

    unsupported = await request(
        app, "POST", "/api/claw/general", uid=OWNER,
        json_body={
            "messages": [{"role": "user", "content": "안녕"}],
            "custom": {"provider": PROVIDER_ID, "model": "opencode-go/not-a-model"},
        },
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "custom_provider_unsupported"

    anonymous = await request(
        app, "POST", "/api/claw/general",
        json_body={
            "messages": [{"role": "user", "content": "안녕"}],
            "custom": custom(),
        },
    )
    assert anonymous.status_code == 401

    assert recorder.requests == []
    assert B14Bomb.touches == 0
    assert AdapterBomb.calls == 0


@pytest.mark.asyncio
async def test_claw_without_custom_keeps_the_managed_p01_lane():
    from test_b54_claw_general_p01_routing import _make_adapter

    adapter = _make_adapter()
    app, _, _, recorder = build_app(adapter=adapter)

    response = await request(
        app, "POST", "/api/claw/general", uid=OWNER,
        json_body={"messages": [{"role": "user", "content": "일반 요청입니다."}], "tier": "plus"},
    )
    assert response.status_code == 200, response.text
    assert "P01 결과" in response.text
    assert adapter.execute.await_count == 1
    assert recorder.requests == []


# ---------------------------------------------------------------------------
# B66 quote interpretation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b66_quote_custom_calls_provider_directly():
    recorder = provider_json(
        {"recipient": {"company": "ABC건설"}, "items": [{"name": "배관", "qty": 20, "unitPrice": 30000}]}
    )
    interpreter = RecordingInterpreter()
    app, _, credential_store, recorder = build_app(
        recorder=recorder, interpreter=interpreter, quote_store=QuoteStore(),
    )
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)

    response = await request(
        app, "POST", "/api/b66/quote/interpret", uid=OWNER,
        json_body={
            "saved_skill_id": SAVED_ID,
            "message": "ABC건설에 배관 20개 단가 30000원",
            "custom": custom(),
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-B66-Result-Origin"] == "custom_provider_direct"
    assert response.json()["candidate"]["items"][0]["name"] == "배관"
    assert CUSTOM_KEY not in response.text
    assert interpreter.calls == []
    assert B14Bomb.touches == 0

    assert len(recorder.requests) == 1
    wire = recorder.requests[0]
    assert wire.headers["authorization"] == "Bearer " + CUSTOM_KEY
    sent = json.loads(wire.content)
    assert sent["model"] == "beam-free"
    assert "견적 입력값 추출기" in sent["messages"][0]["content"]
    assert sent["messages"][1] == {"role": "user", "content": "ABC건설에 배관 20개 단가 30000원"}


@pytest.mark.asyncio
async def test_b66_quote_custom_rejects_conflict_and_missing_key():
    interpreter = RecordingInterpreter()
    app, _, _, recorder = build_app(interpreter=interpreter, quote_store=QuoteStore())

    conflict = await request(
        app, "POST", "/api/b66/quote/interpret", uid=OWNER,
        json_body={
            "saved_skill_id": SAVED_ID,
            "message": "견적",
            "model_id": B66_MODEL,
            "custom": custom(),
        },
    )
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "custom_selection_conflict"

    missing = await request(
        app, "POST", "/api/b66/quote/interpret", uid=OWNER,
        json_body={"saved_skill_id": SAVED_ID, "message": "견적", "custom": custom()},
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "custom_credential_required"

    assert interpreter.calls == []
    assert recorder.requests == []
    assert B14Bomb.touches == 0


@pytest.mark.asyncio
async def test_b66_quote_without_custom_keeps_the_managed_interpreter():
    interpreter = RecordingInterpreter()
    app, _, _, recorder = build_app(interpreter=interpreter, quote_store=QuoteStore())

    response = await request(
        app, "POST", "/api/b66/quote/interpret", uid=OWNER,
        json_body={
            "saved_skill_id": SAVED_ID,
            "message": "ABC건설에 배관 20개",
            "model_id": B66_MODEL,
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-B66-Result-Origin"] == "registered_model_completion"
    assert len(interpreter.calls) == 1
    assert recorder.requests == []


# ---------------------------------------------------------------------------
# B66 AI chat
# ---------------------------------------------------------------------------


def ai_chat_payload(**extra) -> dict:
    body = {"messages": [{"role": "user", "content": "안녕하세요"}], "custom": custom()}
    body.update(extra)
    return body


@pytest.mark.asyncio
async def test_b66_ai_chat_custom_calls_provider_directly_and_persists():
    app, _, credential_store, recorder = build_app()
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)

    response = await request(
        app, "POST", "/api/b66/ai/chat", uid=OWNER, json_body=ai_chat_payload(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["answer"] == "custom 답변"
    assert body["model_id"] == MODEL_ID
    assert body["model_origin"] == "custom_provider_direct"
    assert body["saved_quote"] is False
    assert body["dialogue_saved"] is True
    assert body["conversation_id"].startswith("chat_")
    assert CUSTOM_KEY not in response.text
    assert B14Bomb.touches == 0

    wire = recorder.requests[0]
    assert str(wire.url) == "https://opencode.ai/inference/go/v1/chat/completions"
    assert wire.headers["authorization"] == "Bearer " + CUSTOM_KEY
    sent = json.loads(wire.content)
    assert sent["model"] == "beam-free"
    assert sent["messages"][-1] == {"role": "user", "content": "안녕하세요"}


@pytest.mark.asyncio
async def test_b66_ai_chat_custom_rejects_conflict_and_missing_key():
    app, _, _, recorder = build_app()

    conflict = await request(
        app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload(tier="plus"),
    )
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "custom_selection_conflict"

    missing = await request(
        app, "POST", "/api/b66/ai/chat", uid=OWNER, json_body=ai_chat_payload(),
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "custom_credential_required"

    anonymous = await request(
        app, "POST", "/api/b66/ai/chat", json_body=ai_chat_payload(),
    )
    assert anonymous.status_code == 401

    assert recorder.requests == []
    assert B14Bomb.touches == 0


@pytest.mark.asyncio
async def test_b66_ai_chat_without_custom_keeps_the_managed_lane():
    from test_b66_ai_chat_routes_4466 import FakeDialogueClient, FakeResolver

    app, _, _, recorder = build_app()
    resolver, model = FakeResolver(), FakeDialogueClient()
    app.state.b66_quote_model_resolver = resolver
    app.state.b14_client = model
    app.state.b14_catalog_source = None

    response = await request(
        app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body={
            "model_id": B66_MODEL,
            "messages": [{"role": "user", "content": "안녕하세요"}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_origin"] == "registered_model_completion"
    assert body["answer"] == "AI 대화 응답"
    assert len(resolver.calls) == 1
    assert len(model.calls) == 1
    assert recorder.requests == []
