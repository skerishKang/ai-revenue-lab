"""#5121 PADIEM Custom (BYOK) Claw and B66 product integration E2E.

One real ASGI app (``create_app``) runs every product entry point:

* Claw ``/api/claw/general`` (SSE), its owner conversation, and the absence of
  an unscoped Engine run receipt,
* B66 ``/api/b66/quote/interpret`` over a real saved quote skill,
* B66 ``/api/b66/ai/chat`` with the durable per-turn claim and dialogue save,

against the real ``D1HistoryStore``, ``D1SavedQuoteSkillStore``,
``D1CustomProviderCredentialStore`` and the D1-backed B66 conversation/attempt
stores, all over SQLite carrying the checked-in migrations. Only the provider
transport is substituted (``httpx.MockTransport``), so a pass is
``PRODUCT_E2E_BYOK=INTEGRATION_MOCK`` and never a LIVE customer call.

B14, its router/registry/catalog/policy and the Claw P01 adapter are replaced
with failing probes: the BYOK path must complete with zero touches, and the
managed lanes are deliberately not exercised here.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.b66_ai_chat_routes import reset_dialogue_idempotency
from app.b66_saved_quote_skill_store import (
    D1SavedQuoteSkillStore,
    canonicalize_approved_artifact,
)
from app.byok_client import CustomProviderClient
from app.byok_credentials import D1CustomProviderCredentialStore
from app.history import D1HistoryStore, PRODUCT_SCOPE_B66, PRODUCT_SCOPE_CHAT
from app.main import create_app
from test_5002_byok_product_e2e import (
    CUSTOM_KEY,
    CUSTOM_KEY_SECRET,
    DEFAULT_ANSWER,
    MODEL_ID,
    ORIGIN,
    OTHER,
    OTHER_KEY,
    OWNER,
    PROVIDER_ID,
    ROTATED_KEY,
    SESSION_SECRET,
    FakeAuthenticatedCipher,
    ProviderRecorder,
    SQLiteD1,
    Statement,
    request,
    settings,
    sse_events,
)

SAVED_SKILL_ID_VALUE = "saved-skill-e2e"
SAVED_SKILL_NAME = "E2E 견적서"
SKILL_FINGERPRINT = "e" * 64
PROVIDER_MODEL_WIRE = "beam-free"
QUOTE_CANDIDATE = {
    "recipient": {"company": "ABC건설"},
    "items": [{"name": "배관", "qty": 20, "unitPrice": 30000}],
}
TURN_TOKEN = "0123456789abcdef0123456789abcdef"

EXTRA_MIGRATIONS = (
    "009_claw_run_history.sql",
    "014_claw_run_history_conversation.sql",
    "015_claw_run_history_workspace.sql",
    "021_b66_saved_quote_skill.sql",
    "079_b66_saved_quote_skill_kind.sql",
    "023_b66_company_profile.sql",
    "044_b66_ai_turn_attempt.sql",
)


class MetaStatement(Statement):
    """D1 statement whose ``run`` also reports the D1 ``meta.changes`` shape."""

    async def run(self):
        cursor = self._execute()
        rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
        changes = cursor.rowcount
        self.conn.commit()
        return {"results": rows, "meta": {"changes": changes}}


class IntegrationD1(SQLiteD1):
    """SQLite D1 with the Claw run, quote-skill and B66 attempt migrations."""

    def __init__(self):
        super().__init__()
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        for name in EXTRA_MIGRATIONS:
            self.conn.executescript((migrations / name).read_text(encoding="utf-8"))
        self.conn.commit()

    def prepare(self, query: str) -> MetaStatement:
        return MetaStatement(self.conn, query)

    def conversations_with_scope(self) -> list[dict]:
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT id, user_id, product_scope FROM conversations ORDER BY created_at, id"
            )
        ]

    def claw_runs(self) -> list[dict]:
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT user_id, run_id, action, title, status, result_summary, conversation_id "
                "FROM claw_run_history ORDER BY created_at"
            )
        ]

    def attempt_rows(self) -> list[dict]:
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT user_id, turn_token, model_id, request_digest, state, conversation_id "
                "FROM b66_ai_turn_attempt ORDER BY created_at"
            )
        ]


class B14Probe:
    """Failing B14 client; any BYOK dispatch through it is counted and refused."""

    def __init__(self):
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("b14_injected_failure")

    def stream_text_auto(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("b14_injected_failure")

    def with_guard(self, guard):
        self.calls += 1
        raise AssertionError("B14 guard path entered on BYOK_DIRECT")


class CatalogBomb:
    def __init__(self):
        self.calls = 0

    async def list_registered_models(self):
        self.calls += 1
        raise AssertionError("B14 catalog read on BYOK_DIRECT")

    async def list_selectable_models(self):
        self.calls += 1
        raise AssertionError("B14 catalog read on BYOK_DIRECT")


class ResolverBomb:
    def __init__(self):
        self.calls = 0

    async def resolve_quote_model(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("B14 model router entered on BYOK_DIRECT")


class PolicyBomb:
    def __init__(self):
        self.calls = 0

    async def snapshot(self, workspace_id):
        self.calls += 1
        raise AssertionError("B14 model policy read on BYOK_DIRECT")


class AdapterBomb:
    """Any P01 Engine dispatch on the Claw BYOK path is a contract violation."""

    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        type(self).calls += 1
        raise AssertionError(f"P01 adapter touched on BYOK_DIRECT: {name}")


class InterpreterBomb:
    """The managed B66 interpreter must not run for a custom selection."""

    def __init__(self):
        self.calls = 0

    async def interpret(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("managed B66 interpreter entered on BYOK_DIRECT")


def provider_handler(provider_request: httpx.Request) -> httpx.Response:
    body = json.loads(provider_request.content)
    system = body["messages"][0]["content"]
    if "견적 입력값 추출기" in system:
        content = json.dumps(QUOTE_CANDIDATE, ensure_ascii=False)
    else:
        content = DEFAULT_ANSWER
    return httpx.Response(
        200,
        json={
            "model": PROVIDER_MODEL_WIRE,
            "choices": [{"message": {"content": content}}],
        },
    )


class Harness:
    def __init__(self, recorder=None):
        self.d1 = IntegrationD1()
        self.history = D1HistoryStore(self.d1)
        self.skill_store = D1SavedQuoteSkillStore(self.d1)
        self.credential_store = D1CustomProviderCredentialStore(
            self.d1,
            key_secret=CUSTOM_KEY_SECRET,
            session_secret=SESSION_SECRET,
            cipher=FakeAuthenticatedCipher(),
        )
        self.recorder = recorder or ProviderRecorder(provider_handler)
        self.b14 = B14Probe()
        self.catalog = CatalogBomb()
        self.resolver = ResolverBomb()
        self.policy = PolicyBomb()
        self.adapter = AdapterBomb()
        self.interpreter = InterpreterBomb()
        self.app = create_app(
            settings(),
            d1_binding=self.d1,
            history_store=self.history,
            b66_saved_quote_skill_store=self.skill_store,
            claw_p01_adapter=self.adapter,
            b66_quote_interpreter=self.interpreter,
            custom_credential_store=self.credential_store,
            custom_provider_client=CustomProviderClient(
                transport=self.recorder.transport
            ),
        )
        self.app.state.b14_client = self.b14
        self.app.state.b14_catalog_source = self.catalog
        self.app.state.b66_quote_model_resolver = self.resolver
        self.app.state.central_model_policy_store = self.policy
        self.app.state.usage_gate_enforced = False
        reset_dialogue_idempotency()

    @property
    def b14_calls(self) -> int:
        return self.b14.calls + self.catalog.calls + self.resolver.calls + self.policy.calls

    def assert_no_managed_dispatch(self):
        assert self.b14_calls == 0
        assert self.adapter.calls == 0
        assert self.interpreter.calls == 0


def custom() -> dict[str, str]:
    return {"provider": PROVIDER_ID, "model": MODEL_ID}


async def save_key(app, uid: str, api_key: str):
    response = await request(
        app, "PUT", "/api/chat/custom/credential", uid=uid,
        json_body={"provider": PROVIDER_ID, "api_key": api_key},
    )
    assert response.status_code == 200, response.text
    return response


async def seed_saved_skill(store: D1SavedQuoteSkillStore, uid: str) -> str:
    payload = {
        "schemaVersion": 1,
        "id": SAVED_SKILL_ID_VALUE,
        "name": SAVED_SKILL_NAME,
        "fingerprint": SKILL_FINGERPRINT,
        "approval": {
            "status": "approved",
            "skillFingerprint": SKILL_FINGERPRINT,
        },
        "rendererContract": "quote-template-renderer.v1",
        "calculationAuthority": "quote-core",
        "fixedDefaults": {"taxMode": "EXCLUSIVE"},
        "variableSchema": {
            "recipient": True,
            "quoteNo": True,
            "issueDate": True,
            "items": True,
            "memo": True,
            "taxMode": True,
        },
    }
    artifact = canonicalize_approved_artifact(
        skill_id=SAVED_SKILL_ID_VALUE,
        skill_name=SAVED_SKILL_NAME,
        fingerprint=SKILL_FINGERPRINT,
        version=1,
        serialized_json=json.dumps(payload, ensure_ascii=False),
    )
    saved = await store.put_approved_skill(
        user_id=uid, workspace_id=f"owner:{uid}", artifact=artifact,
    )
    return saved["saved_skill_id"]


def claw_payload(content: str, *, conversation_id: str | None = None) -> dict:
    body = {
        "messages": [{"role": "user", "content": content}],
        "custom": custom(),
    }
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return body


def ai_chat_payload(
    content: str = "안녕하세요",
    *,
    conversation_id: str | None = None,
    turn_token: str = TURN_TOKEN,
) -> dict:
    body = {
        "messages": [{"role": "user", "content": content}],
        "turn_token": turn_token,
        "custom": custom(),
    }
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return body


def last_provider_messages(recorder: ProviderRecorder, index: int) -> list[dict]:
    return json.loads(recorder.requests[index].content)["messages"]


# ---------------------------------------------------------------------------
# Claw: real conversation save/restore, no unscoped run receipt, SSE contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claw_byok_saves_restores_and_keeps_the_sse_contract():
    harness = Harness()
    await save_key(harness.app, OWNER, CUSTOM_KEY)

    first = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("첫 번째 Claw 질문"),
    )
    assert first.status_code == 200, first.text
    events = sse_events(first.text)
    assert [name for name, _ in events] == ["delta", "done"]
    assert events[0][1] == {"delta": DEFAULT_ANSWER}
    conversation_id = events[1][1]["conversation_id"]
    assert conversation_id.startswith("chat_")
    assert CUSTOM_KEY not in first.text

    stored = harness.d1.conversations_with_scope()
    assert stored == [
        {"id": conversation_id, "user_id": OWNER, "product_scope": PRODUCT_SCOPE_CHAT}
    ]
    assert [row["role"] for row in harness.d1.messages(conversation_id)] == [
        "user", "assistant",
    ]

    # The custom lane dispatches no P01 Engine run and resolves no workspace
    # authority, so the completed-run projection fails closed instead of
    # fabricating an unscoped Engine receipt.
    assert harness.d1.claw_runs() == []
    history = await request(harness.app, "GET", "/api/claw/runs", uid=OWNER)
    assert history.status_code == 200, history.text
    assert history.json()["runs"] == []

    second = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("두 번째 Claw 질문", conversation_id=conversation_id),
    )
    assert second.status_code == 200, second.text
    assert sse_events(second.text)[1][1]["conversation_id"] == conversation_id

    # The browser sent only the new turn: prior turns came from the owner store.
    context = last_provider_messages(harness.recorder, 1)[-1]["content"]
    assert "동일 소유자의 이전 대화" in context
    assert "첫 번째 Claw 질문" in context
    assert DEFAULT_ANSWER in context
    assert "두 번째 Claw 질문" in context
    assert [row["role"] for row in harness.d1.messages(conversation_id)] == [
        "user", "assistant", "user", "assistant",
    ]
    assert harness.recorder.authorization(1) == "Bearer " + CUSTOM_KEY
    harness.assert_no_managed_dispatch()


@pytest.mark.asyncio
async def test_claw_byok_isolates_owner_keys_conversations_and_runs():
    harness = Harness()
    await save_key(harness.app, OWNER, CUSTOM_KEY)
    await save_key(harness.app, OTHER, OTHER_KEY)

    owner_turn = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("소유자 Claw 질문"),
    )
    other_turn = await request(
        harness.app, "POST", "/api/claw/general", uid=OTHER,
        json_body=claw_payload("다른 고객 Claw 질문"),
    )
    assert owner_turn.status_code == 200 and other_turn.status_code == 200
    owner_cid = sse_events(owner_turn.text)[1][1]["conversation_id"]
    other_cid = sse_events(other_turn.text)[1][1]["conversation_id"]
    assert owner_cid != other_cid
    assert harness.recorder.authorization(0) == "Bearer " + CUSTOM_KEY
    assert harness.recorder.authorization(1) == "Bearer " + OTHER_KEY

    assert {row["id"]: row["user_id"] for row in harness.d1.conversations_with_scope()} == {
        owner_cid: OWNER,
        other_cid: OTHER,
    }
    assert harness.d1.claw_runs() == []
    assert CUSTOM_KEY.encode() not in b"".join(
        value.encode() for value in harness.d1.sealed_credentials()
    )

    leaked_read = await request(
        harness.app, "GET", f"/api/conversations/{owner_cid}", uid=OTHER
    )
    assert leaked_read.status_code == 404

    before = len(harness.recorder.requests)
    leaked_continue = await request(
        harness.app, "POST", "/api/claw/general", uid=OTHER,
        json_body=claw_payload("남의 Claw 대화 이어쓰기", conversation_id=owner_cid),
    )
    assert leaked_continue.status_code == 404
    assert leaked_continue.json()["error"]["code"] == "conversation_not_found"
    assert len(harness.recorder.requests) == before

    owner_convs = await request(harness.app, "GET", "/api/conversations", uid=OWNER)
    other_convs = await request(harness.app, "GET", "/api/conversations", uid=OTHER)
    assert [row["id"] for row in owner_convs.json()["conversations"]] == [owner_cid]
    assert [row["id"] for row in other_convs.json()["conversations"]] == [other_cid]
    harness.assert_no_managed_dispatch()


@pytest.mark.asyncio
async def test_claw_byok_never_bypasses_the_tool_or_live_approval_boundary():
    harness = Harness()
    await save_key(harness.app, OWNER, CUSTOM_KEY)

    tool = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("내 PC 파일 목록 보여줘"),
    )
    assert tool.status_code == 422
    assert tool.json()["error"]["code"] == "custom_tool_unsupported"

    live = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("안녕하세요"),
        headers={"X-Padiem-Claw-Live": "p01-events-v1"},
    )
    assert live.status_code == 422
    assert live.json()["error"]["code"] == "custom_live_unsupported"

    assert harness.recorder.requests == []
    assert harness.d1.conversations_with_scope() == []
    assert harness.d1.claw_runs() == []
    harness.assert_no_managed_dispatch()


# ---------------------------------------------------------------------------
# B66 quote: real saved skill, candidate contract, no B14, owner isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b66_quote_byok_uses_real_saved_skill_and_returns_candidate_contract():
    harness = Harness()
    await save_key(harness.app, OWNER, CUSTOM_KEY)
    saved_skill_id = await seed_saved_skill(harness.skill_store, OWNER)

    response = await request(
        harness.app, "POST", "/api/b66/quote/interpret", uid=OWNER,
        json_body={
            "saved_skill_id": saved_skill_id,
            "message": "ABC건설에 배관 20개 단가 30000원",
            "custom": custom(),
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-B66-Result-Origin"] == "custom_provider_direct"
    assert CUSTOM_KEY not in response.text
    body = response.json()
    assert body["ok"] is True
    assert body["saved_skill"] == {
        "saved_skill_id": saved_skill_id,
        "skill_id": SAVED_SKILL_ID_VALUE,
        "skill_name": SAVED_SKILL_NAME,
        "skill_fingerprint": SKILL_FINGERPRINT,
        "skill_version": 1,
    }
    assert body["candidate"]["recipient"]["company"] == "ABC건설"
    assert body["candidate"]["items"][0]["name"] == "배관"
    assert body["execution"] == {
        "source_document_parse_calls": 0,
        "server_total_calculation": False,
        "server_rendering": False,
        "browser_quote_core_required": True,
        "browser_approved_renderer_required": True,
    }

    assert len(harness.recorder.requests) == 1
    wire = harness.recorder.requests[0]
    assert wire.headers["authorization"] == "Bearer " + CUSTOM_KEY
    sent = json.loads(wire.content)
    assert sent["model"] == PROVIDER_MODEL_WIRE
    assert "견적 입력값 추출기" in sent["messages"][0]["content"]
    assert sent["messages"][1] == {
        "role": "user", "content": "ABC건설에 배관 20개 단가 30000원",
    }
    assert harness.d1.conversations_with_scope() == []
    harness.assert_no_managed_dispatch()


@pytest.mark.asyncio
async def test_b66_quote_byok_keeps_the_saved_skill_owner_scoped():
    harness = Harness()
    await save_key(harness.app, OWNER, CUSTOM_KEY)
    await save_key(harness.app, OTHER, OTHER_KEY)
    owner_skill_id = await seed_saved_skill(harness.skill_store, OWNER)

    leaked = await request(
        harness.app, "POST", "/api/b66/quote/interpret", uid=OTHER,
        json_body={
            "saved_skill_id": owner_skill_id,
            "message": "ABC건설에 배관 20개",
            "custom": custom(),
        },
    )
    assert leaked.status_code == 404
    assert leaked.json()["error"]["code"] == "saved_quote_skill_not_found"
    assert harness.recorder.requests == []

    own_skill_id = await seed_saved_skill(
        D1SavedQuoteSkillStore(harness.d1), OTHER,
    )
    own = await request(
        harness.app, "POST", "/api/b66/quote/interpret", uid=OTHER,
        json_body={
            "saved_skill_id": own_skill_id,
            "message": "ABC건설에 배관 20개",
            "custom": custom(),
        },
    )
    assert own.status_code == 200, own.text
    assert harness.recorder.authorization(0) == "Bearer " + OTHER_KEY
    harness.assert_no_managed_dispatch()


# ---------------------------------------------------------------------------
# B66 AI chat: dialogue persistence and the durable duplicate-request gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b66_ai_chat_byok_persists_dialogue_and_replays_the_same_turn_token():
    harness = Harness()
    await save_key(harness.app, OWNER, CUSTOM_KEY)

    first = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload("첫 번째 B66 질문"),
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["ok"] is True
    assert body["answer"] == DEFAULT_ANSWER
    assert body["model_id"] == MODEL_ID
    assert body["model_origin"] == "custom_provider_direct"
    assert body["dialogue_saved"] is True
    conversation_id = body["conversation_id"]
    assert conversation_id.startswith("chat_")
    assert CUSTOM_KEY not in first.text

    assert harness.d1.conversations_with_scope() == [
        {"id": conversation_id, "user_id": OWNER, "product_scope": PRODUCT_SCOPE_B66}
    ]
    assert [row["role"] for row in harness.d1.messages(conversation_id)] == [
        "user", "assistant",
    ]
    attempts = harness.d1.attempt_rows()
    assert len(attempts) == 1
    assert attempts[0]["user_id"] == OWNER
    assert attempts[0]["turn_token"] == TURN_TOKEN
    assert attempts[0]["state"] == "completed"
    assert attempts[0]["conversation_id"] == conversation_id
    assert "첫 번째 B66 질문" not in attempts[0]["request_digest"]
    assert len(attempts[0]["request_digest"]) == 64

    # Simulate a different Worker isolate: the in-memory recall is gone, so the
    # D1 completed claim and the stored dialogue alone must answer the retry.
    reset_dialogue_idempotency()
    replay = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload("첫 번째 B66 질문"),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["conversation_id"] == conversation_id
    assert replay.json()["answer"] == DEFAULT_ANSWER
    assert len(harness.recorder.requests) == 1
    assert len(harness.d1.messages(conversation_id)) == 2
    harness.assert_no_managed_dispatch()


@pytest.mark.asyncio
async def test_b66_ai_chat_byok_rejects_a_reused_turn_token_for_other_text():
    harness = Harness()
    await save_key(harness.app, OWNER, CUSTOM_KEY)

    first = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload("원래 질문"),
    )
    assert first.status_code == 200

    reset_dialogue_idempotency()
    conflict = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload("다른 질문"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "dialogue_attempt_mismatch"
    assert len(harness.recorder.requests) == 1
    assert len(harness.d1.attempt_rows()) == 1
    harness.assert_no_managed_dispatch()


@pytest.mark.asyncio
async def test_b66_ai_chat_byok_isolates_owner_key_conversation_and_turn_token():
    harness = Harness()
    await save_key(harness.app, OWNER, CUSTOM_KEY)
    await save_key(harness.app, OTHER, OTHER_KEY)

    owner_turn = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload("소유자 B66 질문"),
    )
    other_turn = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OTHER,
        json_body=ai_chat_payload("다른 고객 B66 질문"),
    )
    assert owner_turn.status_code == 200 and other_turn.status_code == 200
    owner_cid = owner_turn.json()["conversation_id"]
    other_cid = other_turn.json()["conversation_id"]
    assert owner_cid != other_cid
    assert harness.recorder.authorization(0) == "Bearer " + CUSTOM_KEY
    assert harness.recorder.authorization(1) == "Bearer " + OTHER_KEY

    before = len(harness.recorder.requests)
    leaked = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OTHER,
        json_body=ai_chat_payload(
            "남의 B66 대화 이어쓰기", conversation_id=owner_cid,
            turn_token="f" * 32,
        ),
    )
    assert leaked.status_code == 404
    assert leaked.json()["error"]["code"] == "conversation_not_found"
    assert len(harness.recorder.requests) == before

    assert {row["id"]: row["user_id"] for row in harness.d1.conversations_with_scope()} == {
        owner_cid: OWNER,
        other_cid: OTHER,
    }
    harness.assert_no_managed_dispatch()


# ---------------------------------------------------------------------------
# B14 failure injection across every BYOK product entrance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_byok_products_complete_with_failing_b14_router_and_catalog():
    harness = Harness()
    await save_key(harness.app, OWNER, CUSTOM_KEY)
    saved_skill_id = await seed_saved_skill(harness.skill_store, OWNER)

    claw = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("B14 없이 Claw"),
    )
    quote = await request(
        harness.app, "POST", "/api/b66/quote/interpret", uid=OWNER,
        json_body={
            "saved_skill_id": saved_skill_id,
            "message": "ABC건설에 배관 20개",
            "custom": custom(),
        },
    )
    chat = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload("B14 없이 B66 대화"),
    )

    assert claw.status_code == 200, claw.text
    assert quote.status_code == 200, quote.text
    assert chat.status_code == 200, chat.text
    assert len(harness.recorder.requests) == 3
    harness.assert_no_managed_dispatch()


# ---------------------------------------------------------------------------
# Key rotation/deletion and provider failure per product
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_byok_key_rotation_and_deletion_apply_to_every_product():
    harness = Harness()
    saved_skill_id = await seed_saved_skill(harness.skill_store, OWNER)
    await save_key(harness.app, OWNER, CUSTOM_KEY)

    first = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("회전 전 Claw"),
    )
    assert first.status_code == 200
    assert harness.recorder.authorization(0) == "Bearer " + CUSTOM_KEY

    rotated = await save_key(harness.app, OWNER, ROTATED_KEY)
    assert rotated.json()["credential"]["key_last4"] == ROTATED_KEY[-4:]

    second = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("회전 후 Claw"),
    )
    assert second.status_code == 200
    assert harness.recorder.authorization(1) == "Bearer " + ROTATED_KEY

    deleted = await request(
        harness.app, "DELETE", f"/api/chat/custom/credential?provider={PROVIDER_ID}",
        uid=OWNER,
    )
    assert deleted.status_code == 200

    before = len(harness.recorder.requests)
    conversations_before = harness.d1.conversations_with_scope()
    refused_claw = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("삭제 후 Claw"),
    )
    refused_quote = await request(
        harness.app, "POST", "/api/b66/quote/interpret", uid=OWNER,
        json_body={
            "saved_skill_id": saved_skill_id,
            "message": "삭제 후 견적",
            "custom": custom(),
        },
    )
    refused_chat = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload("삭제 후 B66", turn_token="b" * 32),
    )
    for response in (refused_claw, refused_quote, refused_chat):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "custom_credential_required"
    assert len(harness.recorder.requests) == before
    assert harness.d1.conversations_with_scope() == conversations_before
    harness.assert_no_managed_dispatch()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_status", "expected_status", "code"),
    [
        (429, 429, "custom_provider_rate_limited"),
        (500, 502, "custom_provider_unavailable"),
    ],
)
async def test_provider_failures_keep_each_product_side_effect_free(
    provider_status, expected_status, code,
):
    recorder = ProviderRecorder(
        lambda provider_request: httpx.Response(
            provider_status, json={"error": "vendor-detail"}
        )
    )
    harness = Harness(recorder=recorder)
    saved_skill_id = await seed_saved_skill(harness.skill_store, OWNER)
    await save_key(harness.app, OWNER, CUSTOM_KEY)

    claw = await request(
        harness.app, "POST", "/api/claw/general", uid=OWNER,
        json_body=claw_payload("공급사 오류 Claw"),
    )
    quote = await request(
        harness.app, "POST", "/api/b66/quote/interpret", uid=OWNER,
        json_body={
            "saved_skill_id": saved_skill_id,
            "message": "공급사 오류 견적",
            "custom": custom(),
        },
    )
    chat = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload("공급사 오류 B66"),
    )

    for response in (claw, quote, chat):
        assert response.status_code == expected_status
        assert response.json()["error"]["code"] == code
        assert "vendor" not in response.text

    assert harness.d1.conversations_with_scope() == []
    assert harness.d1.claw_runs() == []
    assert len(recorder.requests) == 3

    # The failed B66 turn stays permanently claimed: an uncertain provider
    # outcome must never be retried into a second charged call.
    reset_dialogue_idempotency()
    retried = await request(
        harness.app, "POST", "/api/b66/ai/chat", uid=OWNER,
        json_body=ai_chat_payload("공급사 오류 B66"),
    )
    assert retried.status_code == 409
    assert retried.json()["error"]["code"] == "dialogue_turn_in_progress"
    assert len(recorder.requests) == 3
    assert harness.d1.attempt_rows()[0]["state"] == "claimed"
    harness.assert_no_managed_dispatch()
