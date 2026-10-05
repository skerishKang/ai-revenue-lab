"""Network-free tests for authenticated B66 conversation-to-quote runtime (#3303)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b14_client import B14Client
from app.b66_quote_conversation import (
    B66QuoteConversationError,
    B66QuoteConversationInterpreter,
    B66QuoteConversationProjection,
    MAX_MODEL_WRAPPER_CHARS,
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

    # 요약 단가도 detailGroup 도 없는 item 은 partial 로 보존한다 (#3391).
    # 값을 추정하거나 0 으로 채우지 않고 missing 으로 다음 입력을 요청한다.
    partial_summary = normalize_conversation_output(
        {
            "recipient": {"company": "ABC건설"},
            "items": [{"name": "요약 공사", "qty": 1, "unitPrice": None}],
            "detailGroups": [],
            "missing": [],
        }
    ).safe_dict()
    assert partial_summary["recipient"]["company"] == "ABC건설"
    assert partial_summary["items"][0]["name"] == "요약 공사"
    assert partial_summary["items"][0]["qty"] == 1
    assert "unitPrice" not in partial_summary["items"][0]
    assert partial_summary["items"][0].get("unitPrice") != 0

    with pytest.raises(B66QuoteConversationError, match="incomplete_item"):
        normalize_conversation_output(
            {
                "recipient": {"company": "ABC건설"},
                "items": [{"name": "요약 공사", "qty": None, "unitPrice": 1000}],
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
    assert call["skill"] is not None
    assert call["skill"].id == "b66-quote-extract"
    assert call["skill"].max_tokens == 2048
    assert call["skill"].system_instruction is None


@pytest.mark.asyncio
async def test_b66_extraction_budget_reaches_the_actual_b14_request_payload():
    seen = {}

    async def handler(request):
        body = json.loads(request.content)
        seen["body"] = body
        answer = json.dumps(
            {
                "recipient": {"company": "대한건설"},
                "items": [{"name": "배관", "qty": 100, "unitPrice": None}],
                "detailGroups": [],
                "missing": [],
            },
            ensure_ascii=False,
        )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": answer}}
                ],
                "business14": {
                    "request_id": "b14req_b66_budget_test",
                    "route_mode": "manual",
                    "selected_model": body["model"],
                    "selected_provider": "Kilo Gateway / Stealth",
                },
            },
        )

    client = B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    result = await B66QuoteConversationInterpreter(client).interpret(
        message="대한건설에 배관 100미터, 부가세 별도",
        skill=_skill(),
    )

    assert seen["body"]["max_tokens"] == 2048
    assert seen["body"]["business14"]["max_attempts"] == 1
    assert seen["body"]["business14"]["allow_external_fallback"] is False
    assert result.recipient["company"] == "대한건설"
    assert "unitPrice" in result.missing


@pytest.mark.asyncio
async def test_interpreter_keeps_partial_item_and_reports_missing_unit_price():
    class PartialClient:
        def __init__(self):
            self.calls = []

        async def complete(self, *args, **kwargs):
            self.calls.append(args)
            return {"answer": json.dumps(
                {
                    "recipient": {"company": "대한건설"},
                    "items": [{"name": "배관", "qty": 100, "unitPrice": None}],
                    "detailGroups": [],
                    "missing": [],
                },
                ensure_ascii=False,
            )}

    client = PartialClient()
    result = await B66QuoteConversationInterpreter(client).interpret(
        message="대한건설에 배관 100미터 견적 만들어줘",
        skill=_skill(),
    )
    safe = result.safe_dict()
    # 이미 알아낸 사실은 보존되고, 없는 단가는 추정/계산되지 않는다.
    assert safe["recipient"]["company"] == "대한건설"
    assert safe["items"][0]["name"] == "배관"
    assert safe["items"][0]["qty"] == 100
    assert "unitPrice" not in safe["items"][0]
    assert safe["items"][0].get("unitPrice") != 0
    # missing 은 서버가 파생하며 모델 주장을 신뢰하지 않는다.
    assert "unitPrice" in result.missing
    assert len(client.calls) == 1
    print("PARTIAL_ITEM_FACTS_PRESERVED=YES")
    print("MISSING_UNIT_PRICE_CAN_ENTER_FOLLOWUP=YES")
    print("MODEL_CALCULATES_MISSING_PRICE=NO")


@pytest.mark.asyncio
async def test_interpreter_does_not_report_missing_for_complete_item():
    class CompleteClient:
        def __init__(self):
            self.calls = []

        async def complete(self, *args, **kwargs):
            self.calls.append(args)
            return {"answer": json.dumps(
                {
                    "recipient": {"company": "대한건설"},
                    "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
                    "detailGroups": [],
                    "missing": [],
                },
                ensure_ascii=False,
            )}

    result = await B66QuoteConversationInterpreter(CompleteClient()).interpret(
        message="대한건설에 배관 100미터, 미터당 18000원",
        skill=_skill(),
    )
    assert "unitPrice" not in result.missing
    assert result.safe_dict()["items"][0]["unitPrice"] == 18000


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
async def test_interpreter_rejects_non_json_model_answer():
    class BadClient:
        async def complete(self, *args, **kwargs):
            return {"answer": "견적 합계는 60만원입니다."}

    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        await B66QuoteConversationInterpreter(BadClient()).interpret(
            message="ABC건설 견적",
            skill=_skill(),
        )


_EXTRACT_PAYLOAD = {
    "recipient": {"company": "Synthetic Buyer"},
    "items": [{"name": "Item A", "qty": 2, "unitPrice": 1000}],
    "detailGroups": [],
    "missing": [],
}
_EXTRACT_JSON = json.dumps(_EXTRACT_PAYLOAD, ensure_ascii=False)


def test_normalizer_recovers_only_one_bounded_safe_wrapper():
    # A) exact JSON answer
    exact = normalize_conversation_output(_EXTRACT_JSON).safe_dict()
    assert exact["recipient"]["company"] == "Synthetic Buyer"
    assert exact["items"][0]["qty"] == 2

    # B) one whole-answer JSON fence
    fenced = normalize_conversation_output(f"```json\n{_EXTRACT_JSON}\n```").safe_dict()
    assert fenced["recipient"]["company"] == "Synthetic Buyer"
    assert fenced["items"][0]["unitPrice"] == 1000

    # C) bounded prose around one fenced payload
    wrapped_fence = normalize_conversation_output(
        f"Here is the extracted JSON:\n```json\n{_EXTRACT_JSON}\n```\nThat is all."
    ).safe_dict()
    assert wrapped_fence["recipient"]["company"] == "Synthetic Buyer"
    assert wrapped_fence["items"][0]["unitPrice"] == 1000

    # D) bounded prose around one raw object
    wrapped_raw = normalize_conversation_output(
        f"Extracted quote fields:\n{_EXTRACT_JSON}\nEnd of extraction."
    ).safe_dict()
    assert wrapped_raw["recipient"]["company"] == "Synthetic Buyer"
    assert wrapped_raw["items"][0]["qty"] == 2

    # E) two fenced payloads are ambiguous, not recoverable
    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(
            f"```json\n{_EXTRACT_JSON}\n```\n```json\n{_EXTRACT_JSON}\n```"
        )

    # F) two raw objects are ambiguous, not recoverable
    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(f"{_EXTRACT_JSON}\n{_EXTRACT_JSON}")

    # G) malformed JSON fails truthfully, wrapped or fenced
    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(
            'Result: {"recipient":{},"items":[],"missing":[],}'
        )
    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(
            '```json\n{"recipient":{},"items":[],"missing":[],}\n```'
        )
    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output('Result: {"recipient":{},"items":[')

    # H) server authority fields stay forbidden through the recovery path
    for authority_field in ("total", "sender", "template", "vat"):
        payload = json.dumps(
            {**_EXTRACT_PAYLOAD, authority_field: {"company": "공격자"}},
            ensure_ascii=False,
        )
        with pytest.raises(
            B66QuoteConversationError,
            match="unsupported_output_field|forbidden_output_field",
        ):
            normalize_conversation_output(f"Extracted:\n{payload}")
    with pytest.raises(B66QuoteConversationError, match="forbidden_output_field"):
        normalize_conversation_output(
            'Extracted: {"recipient":{},"items":[{"name":"A","qty":1,'
            '"unitPrice":1,"amount":5}],"missing":[]}'
        )

    # I) the wrapper budget bounds prefix and suffix together
    long_prefix = "a" * (MAX_MODEL_WRAPPER_CHARS + 1)
    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(f"{long_prefix}{_EXTRACT_JSON}")
    half = "b" * (MAX_MODEL_WRAPPER_CHARS // 2 + 1)
    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(f"{half}{_EXTRACT_JSON}\n{half}")

    # J) structural characters in the wrapper always fail closed
    for prefix, suffix in (
        ("[note] ", ""),
        ("", " }"),
        ("", " [1]"),
        ("Here {draft}: ", ""),
    ):
        with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
            normalize_conversation_output(f"{prefix}{_EXTRACT_JSON}{suffix}")
    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        normalize_conversation_output(
            f"Here {{draft}}:\n```json\n{_EXTRACT_JSON}\n```\nDone."
        )


@pytest.mark.asyncio
async def test_interpreter_recovers_one_safe_wrapper_with_one_model_call():
    class WrappedClient:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return {
                "answer": (
                    "Extracted fields:\n```json\n"
                    '{"recipient":{"company":"Synthetic Buyer"},'
                    '"items":[{"name":"Item A","qty":1,"unitPrice":1000}],'
                    '"detailGroups":[],"missing":["unitPrice"]}\n'
                    "```\nDone."
                )
            }

    client = WrappedClient()
    result = await B66QuoteConversationInterpreter(client).interpret(
        message="Synthetic Buyer Item A one unit",
        skill=_skill(),
    )
    safe = result.safe_dict()
    assert safe["recipient"]["company"] == "Synthetic Buyer"
    assert safe["items"][0]["unitPrice"] == 1000
    # 모델이 선언한 missing 은 신뢰하지 않고 서버가 정규화된 사실에서 파생한다.
    assert "unitPrice" not in result.missing
    assert client.calls == 1
    print("SAFE_WRAPPER_MODEL_CALLS=1")
    print("MODEL_MISSING_CLAIM_TRUSTED=NO")


@pytest.mark.asyncio
async def test_interpreter_fails_truthfully_without_retrying_model():
    class MalformedClient:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return {"answer": 'Extracted: {"recipient":{},"items":[],}'}

    malformed = MalformedClient()
    with pytest.raises(B66QuoteConversationError, match="invalid_model_output"):
        await B66QuoteConversationInterpreter(malformed).interpret(
            message="ABC건설 견적",
            skill=_skill(),
        )
    assert malformed.calls == 1

    class FailingClient:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("provider unavailable")

    failing = FailingClient()
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await B66QuoteConversationInterpreter(failing).interpret(
            message="ABC건설 견적",
            skill=_skill(),
        )
    assert failing.calls == 1
    print("MALFORMED_OUTPUT_MODEL_CALLS=1")
    print("PROVIDER_FAILURE_MODEL_CALLS=1")