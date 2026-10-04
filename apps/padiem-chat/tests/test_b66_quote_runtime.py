"""Network-free tests for authenticated B66 conversation-to-quote runtime (#3303)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_quote_conversation import (
    B66QuoteConversationError,
    B66QuoteConversationInterpreter,
    B66QuoteConversationProjection,
    normalize_conversation_output,
)
from app.config import Settings


USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
SAVED_ID = "b66skill_" + "c" * 32


def _settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "b66-runtime.apps.googleusercontent.com",
        "google_client_secret": "b66-runtime-google-secret",
        "session_secret": "b66-runtime-session-secret-not-real-00",
        "session_max_age_seconds": 3600,
        "live_enabled": "false",
    }
    values.update(overrides)
    return Settings.from_values(**values)


def _skill():
    return {
        "schemaVersion": 1,
        "id": "saved-skill-1",
        "name": "우리 견적서",
        "fixedDefaults": {
            "sender": {"company": "테스트상사"},
            "validDays": 30,
            "taxMode": "EXCLUSIVE",
            "memo": "",
        },
        "variableSchema": {
            "recipient": True,
            "quoteNo": True,
            "issueDate": True,
            "items": True,
            "memo": True,
            "taxMode": True,
        },
        "internalTemplate": {
            "id": "template-private",
            "title": {"text": "견 적 서"},
        },
        "approval": {"status": "approved"},
        "fingerprint": "d" * 64,
        "rendererContract": "quote-template-renderer.v1",
        "calculationAuthority": "quote-core",
    }


def _saved_row(*, user_id=USER_A, workspace_id=None):
    workspace = workspace_id or f"owner:{user_id}"
    return {
        "saved_skill_id": SAVED_ID,
        "workspace_id": workspace,
        "skill_id": "saved-skill-1",
        "skill_name": "우리 견적서",
        "skill_fingerprint": "d" * 64,
        "skill_version": 1,
        "status": "approved",
        "skill": _skill(),
    }


class _Store:
    def __init__(self):
        self.rows = {
            (USER_A, f"owner:{USER_A}", SAVED_ID): _saved_row(user_id=USER_A)
        }
        self.calls = []

    async def list_skills(self, *, user_id, workspace_id, limit=20):
        self.calls.append(("list", user_id, workspace_id))
        result = []
        for (uid, wid, _), row in self.rows.items():
            if uid == user_id and wid == workspace_id and row["status"] == "approved":
                result.append({k: v for k, v in row.items() if k != "skill"})
        return result[:limit]

    async def get_skill(self, *, user_id, workspace_id, saved_skill_id):
        self.calls.append(("get", user_id, workspace_id, saved_skill_id))
        return self.rows.get((user_id, workspace_id, saved_skill_id))


class _Interpreter:
    def __init__(self):
        self.calls = []

    async def interpret(self, *, message, skill):
        self.calls.append((message, skill))
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
        )


def _client(store, interpreter, *, user_id=USER_A, signed_in=True):
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_saved_quote_skill_store=store,
        b66_quote_interpreter=interpreter,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    if signed_in:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, user_id),
            domain="chat.example.test",
            path="/",
        )
    return client


def test_routes_registered():
    app = create_app(
        settings=Settings.from_values(
            runtime_mode="mock",
            auth_mode="off",
            live_enabled="false",
        )
    )
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/b66/runtime-config" in paths
    assert "/api/b66/saved-skills" in paths
    assert "/api/b66/saved-skills/{saved_skill_id}" in paths
    assert "/api/b66/quote/interpret" in paths


def test_runtime_config_is_login_required_and_default_off():
    store = _Store()
    interpreter = _Interpreter()
    anonymous = _client(store, interpreter, signed_in=False)
    assert anonymous.get("/api/b66/runtime-config").status_code == 401

    signed_in = _client(store, interpreter)
    response = signed_in.get("/api/b66/runtime-config")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "enabled": False,
        "embed_url": None,
        "origin": None,
    }


def test_runtime_config_projects_only_public_https_embed_location():
    settings = _settings(b66_quote_base_url="https://quote.example.test/")
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_saved_quote_skill_store=_Store(),
        b66_quote_interpreter=_Interpreter(),
    )
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, USER_A),
        domain="chat.example.test",
        path="/",
    )
    response = client.get("/api/b66/runtime-config")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "enabled": True,
        "embed_url": "https://quote.example.test/embed.html",
        "origin": "https://quote.example.test",
    }
    assert "secret" not in response.text.lower()
    assert "token" not in response.text.lower()


def test_anonymous_cannot_list_read_or_interpret():
    store = _Store()
    interpreter = _Interpreter()
    client = _client(store, interpreter, signed_in=False)
    assert client.get("/api/b66/saved-skills").status_code == 401
    assert client.get(f"/api/b66/saved-skills/{SAVED_ID}").status_code == 401
    assert client.post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID, "message": "ABC건설에 배관 20개"},
    ).status_code == 401
    assert store.calls == []
    assert interpreter.calls == []


def test_signed_in_owner_lists_and_reads_only_own_skill():
    store = _Store()
    interpreter = _Interpreter()
    owner = _client(store, interpreter, user_id=USER_A)
    other = _client(store, interpreter, user_id=USER_B)

    listed = owner.get("/api/b66/saved-skills")
    assert listed.status_code == 200
    assert listed.json()["skills"][0]["saved_skill_id"] == SAVED_ID
    assert "skill" not in listed.json()["skills"][0]

    detail = owner.get(f"/api/b66/saved-skills/{SAVED_ID}")
    assert detail.status_code == 200
    assert detail.json()["saved_skill"]["skill"]["id"] == "saved-skill-1"

    assert other.get("/api/b66/saved-skills").json()["skills"] == []
    foreign = other.get(f"/api/b66/saved-skills/{SAVED_ID}")
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "saved_quote_skill_not_found"


def test_conversation_interpretation_returns_variable_candidate_only():
    store = _Store()
    interpreter = _Interpreter()
    client = _client(store, interpreter)

    response = client.post(
        "/api/b66/quote/interpret",
        json={
            "saved_skill_id": SAVED_ID,
            "message": "ABC건설에 배관 20개, 개당 3만원으로 견적 내줘",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["saved_skill"] == {
        "saved_skill_id": SAVED_ID,
        "skill_id": "saved-skill-1",
        "skill_name": "우리 견적서",
        "skill_fingerprint": "d" * 64,
        "skill_version": 1,
    }
    assert body["candidate"]["recipient"]["company"] == "ABC건설"
    assert body["candidate"]["items"] == [
        {"name": "배관", "qty": 20, "unitPrice": 30000}
    ]
    assert body["candidate"]["missing"] == []
    assert "subtotal" not in json.dumps(body, ensure_ascii=False)
    assert "grandTotal" not in json.dumps(body, ensure_ascii=False)
    assert body["execution"] == {
        "source_document_parse_calls": 0,
        "server_total_calculation": False,
        "server_rendering": False,
        "browser_quote_core_required": True,
        "browser_approved_renderer_required": True,
    }
    assert interpreter.calls[0][0].startswith("ABC건설")
    assert interpreter.calls[0][1]["fingerprint"] == "d" * 64


def test_client_cannot_choose_owner_tenant_or_workspace():
    client = _client(_Store(), _Interpreter())
    for forbidden in (
        {"user_id": USER_B},
        {"tenant_id": "tenant_" + "e" * 32},
        {"workspace_id": "owner:" + USER_B},
    ):
        response = client.post(
            "/api/b66/quote/interpret",
            json={
                "saved_skill_id": SAVED_ID,
                "message": "테스트 견적",
                **forbidden,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "forbidden_owner_field"


def test_foreign_skill_never_reaches_interpreter():
    store = _Store()
    interpreter = _Interpreter()
    client = _client(store, interpreter, user_id=USER_B)
    response = client.post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID, "message": "ABC건설 견적"},
    )
    assert response.status_code == 404
    assert interpreter.calls == []


def test_normalizer_accepts_variable_fields_and_rejects_calculated_or_template_output():
    projection = normalize_conversation_output(
        {
            "recipient": {
                "company": "ABC건설",
                "person": None,
                "address": None,
                "email": None,
            },
            "quoteNo": None,
            "issueDate": None,
            "projectName": "스마트팜 환경제어설비",
            "items": [{
                "name": "배관",
                "spec": "40A",
                "unit": "m",
                "qty": 20,
                "unitPrice": 30000,
                "note": "현장 설치",
            }],
            "detailGroups": [{
                "summaryIndex": 1,
                "title": "배관 상세",
                "items": [{
                    "name": "배관 자재",
                    "spec": "40A",
                    "unit": "m",
                    "qty": 20,
                    "unitPrice": 25000,
                    "note": "자재",
                    "section": "1. 자재",
                }, {
                    "name": "설치",
                    "unit": "식",
                    "qty": 1,
                    "unitPrice": 100000,
                    "section": "2. 인건비",
                }],
            }],
            "memo": None,
            "taxMode": None,
            "missing": ["quoteNo", "issueDate"],
        }
    )
    safe = projection.safe_dict()
    assert safe["projectName"] == "스마트팜 환경제어설비"
    assert safe["items"][0]["unitPrice"] == 30000
    assert safe["items"][0]["spec"] == "40A"
    assert safe["items"][0]["unit"] == "m"
    assert safe["items"][0]["note"] == "현장 설치"
    assert safe["detailGroups"][0]["id"] == "detail-group-1"
    assert safe["detailGroups"][0]["summaryItemId"] == "item-1"
    assert safe["detailGroups"][0]["title"] == "배관 상세"
    assert safe["detailGroups"][0]["items"][0]["section"] == "1. 자재"
    assert safe["detailGroups"][0]["items"][1]["unitPrice"] == 100000

    linked_without_summary_price = normalize_conversation_output(
        {
            "recipient": {"company": "ABC건설"},
            "items": [{"name": "요약 공사", "qty": 1, "unitPrice": None}],
            "detailGroups": [{
                "summaryIndex": 1,
                "items": [
                    {"name": "자재", "qty": 2, "unitPrice": 50000},
                    {"name": "설치", "qty": 1, "unitPrice": 30000},
                ],
            }],
            "missing": [],
        }
    ).safe_dict()
    assert linked_without_summary_price["items"][0]["unitPrice"] == 0
    assert linked_without_summary_price["detailGroups"][0]["summaryItemId"] == "item-1"

    with pytest.raises(B66QuoteConversationError, match="incomplete_item"):
        normalize_conversation_output(
            {
                "recipient": {"company": "ABC건설"},
                "items": [{"name": "요약 공사", "qty": 1, "unitPrice": None}],
                "detailGroups": [],
                "missing": [],
            }
        )

    with pytest.raises(B66QuoteConversationError, match="unsupported_output_field|forbidden_output_field"):
        normalize_conversation_output(
            {
                "recipient": {},
                "items": [],
                "missing": [],
                "grandTotal": 600000,
            }
        )
    with pytest.raises(B66QuoteConversationError, match="unsupported_output_field|forbidden_output_field"):
        normalize_conversation_output(
            {
                "recipient": {},
                "items": [],
                "missing": [],
                "sender": {"company": "공격자"},
            }
        )

    with pytest.raises(B66QuoteConversationError, match="forbidden_output_field"):
        normalize_conversation_output(
            {
                "recipient": {"company": "ABC건설"},
                "items": [{
                    "name": "배관",
                    "qty": 1,
                    "unitPrice": 1000,
                    "amount": 1000,
                }],
                "missing": [],
            }
        )

    with pytest.raises(B66QuoteConversationError, match="forbidden_output_field"):
        normalize_conversation_output(
            {
                "recipient": {"company": "ABC건설"},
                "items": [{"name": "요약", "qty": 1, "unitPrice": 1}],
                "detailGroups": [{
                    "summaryIndex": 1,
                    "items": [{"name": "상세", "qty": 1, "unitPrice": 1000, "amount": 1000}],
                }],
                "missing": [],
            }
        )

    with pytest.raises(B66QuoteConversationError, match="invalid_detail_summary_index"):
        normalize_conversation_output(
            {
                "recipient": {"company": "ABC건설"},
                "items": [{"name": "요약", "qty": 1, "unitPrice": 1}],
                "detailGroups": [{
                    "summaryIndex": 2,
                    "items": [{"name": "상세", "qty": 1, "unitPrice": 1000}],
                }],
                "missing": [],
            }
        )



def test_normalizer_accepts_only_bounded_json_fence_numeric_text_and_tax_case():
    fenced = """```json
{"recipient":{"company":"Synthetic Buyer"},"items":[{"name":"Item A","qty":"2","unitPrice":"1000"}],"taxMode":"exclusive","missing":[]}
```"""
    projection = normalize_conversation_output(fenced)
    safe = projection.safe_dict()
    assert safe["recipient"]["company"] == "Synthetic Buyer"
    assert safe["items"][0]["qty"] == 2
    assert safe["items"][0]["unitPrice"] == 1000
    assert safe["taxMode"] == "EXCLUSIVE"

    wrapped = normalize_conversation_output("Here is the JSON:\n" + fenced).safe_dict()
    assert wrapped["recipient"]["company"] == "Synthetic Buyer"
    assert wrapped["items"][0]["unitPrice"] == 1000

    raw_wrapped = normalize_conversation_output(
        "Extracted quote fields:\n"
        '{"recipient":{"company":"Synthetic Buyer"},"items":[{"name":"Item A","qty":2,"unitPrice":1000}],"missing":[]}'
        "\nEnd of extraction."
    ).safe_dict()
    assert raw_wrapped["items"][0]["qty"] == 2

    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(fenced + "\n" + fenced)

    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(
            '{"recipient":{},"items":[],"missing":[]} trailing {"recipient":{}}'
        )

    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(
            'Result: {"recipient":{},"items":[],"missing":[],}'
        )

    with pytest.raises(B66QuoteConversationError, match="unsupported_output_field|forbidden_output_field"):
        normalize_conversation_output(
            'Result: {"recipient":{},"items":[],"missing":[],"sender":{"company":"attacker"}}'
        )

    with pytest.raises(B66QuoteConversationError, match="invalid_number"):
        normalize_conversation_output(
            {
                "recipient": {"company": "Synthetic Buyer"},
                "items": [{"name": "Item A", "qty": "2 units", "unitPrice": "1000"}],
                "missing": [],
            }
        )

    with pytest.raises(B66QuoteConversationError, match="invalid_tax_mode"):
        normalize_conversation_output(
            {
                "recipient": {"company": "Synthetic Buyer"},
                "items": [{"name": "Item A", "qty": "2", "unitPrice": "1000"}],
                "taxMode": "exclusive plus tax",
                "missing": [],
            }
        )


class _FakeB14:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, skill=None, additional_system_context=None, attachments=()):
        self.calls.append(
            {
                "messages": messages,
                "skill": skill,
                "context": additional_system_context,
                "attachments": attachments,
            }
        )
        return {
            "answer": json.dumps(
                {
                    "recipient": {
                        "company": "ABC건설",
                        "person": None,
                        "address": None,
                        "email": None,
                    },
                    "quoteNo": None,
                    "issueDate": None,
                    "items": [{"name": "배관", "qty": 20, "unitPrice": 30000}],
                    "memo": None,
                    "taxMode": None,
                    "missing": [],
                },
                ensure_ascii=False,
            )
        }


@pytest.mark.asyncio
async def test_interpreter_calls_model_once_for_fields_only_and_hides_template_content():
    client = _FakeB14()
    interpreter = B66QuoteConversationInterpreter(client)
    result = await interpreter.interpret(
        message="ABC건설에 배관 20개 개당 3만원",
        skill=_skill(),
    )
    assert result.recipient["company"] == "ABC건설"
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["messages"] == [
        {"role": "user", "content": "ABC건설에 배관 20개 개당 3만원"}
    ]
    context = call["context"]
    assert "금액 합계" in context
    assert "defaultTaxMode" in context
    assert "optionalPresentationFields" in context
    assert "projectName" in context
    assert "items.spec" in context
    assert "items.unit" in context
    assert "items.note" in context
    assert "detailGroups" in context
    assert "summaryIndex" in context
    assert "계산하지 말고 unitPrice를 null" in context
    assert "QuoteCore가 상세 소계를 요약 단가로 파생" in context
    assert "items[].section" not in context or "section" in context
    assert "template-private" not in context
    assert "테스트상사" not in context
    assert call["attachments"] == ()


def test_normalizer_rejects_impossible_calendar_date():
    with pytest.raises(B66QuoteConversationError, match="invalid_issue_date"):
        normalize_conversation_output(
            {
                "recipient": {"company": "ABC건설"},
                "quoteNo": "Q-1",
                "issueDate": "2026-02-30",
                "items": [{"name": "배관", "qty": 1, "unitPrice": 1000}],
                "memo": None,
                "taxMode": None,
                "missing": [],
            }
        )


@pytest.mark.asyncio
async def test_interpreter_repairs_one_safe_wrapper_without_retrying_model():
    class WrappedClient:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return {
                "answer": (
                    "Extracted fields:\n```json\n"
                    '{"recipient":{"company":"Synthetic Buyer"},"items":[{"name":"Item A","qty":1,"unitPrice":1000}],"missing":[]}'
                    "\n```\nDone."
                )
            }

    client = WrappedClient()
    projection = await B66QuoteConversationInterpreter(client).interpret(
        message="Synthetic Buyer Item A one unit",
        skill=_skill(),
    )
    assert projection.recipient["company"] == "Synthetic Buyer"
    assert projection.items[0]["unitPrice"] == 1000
    assert client.calls == 1


@pytest.mark.asyncio
async def test_interpreter_rejects_non_json_model_answer():
    class BadClient:
        async def complete(self, *args, **kwargs):
            return {"answer": "견적 합계는 60만원입니다."}

    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        await B66QuoteConversationInterpreter(BadClient()).interpret(
            message="ABC건설 견적",
            skill=_skill(),
        )