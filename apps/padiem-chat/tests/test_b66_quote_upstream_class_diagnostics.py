"""Focused regression (#3391): bounded 502 upstream-class diagnostics on the B66
interpret route.

The public 502 contract is unchanged (status 502 / code
``quote_interpretation_failed`` / the same Korean message). The response may
additionally carry exactly one allowlisted ``X-B66-Upstream-Class`` header that
names the product-owned ``ChatRuntimeError`` class, so Production can tell a
provider/runtime failure apart without exposing the raw exception, provider
payload, model output or any customer value.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b14_client import ChatRuntimeError
from app.b66_quote_conversation import B66QuoteConversationInterpreter
from app.config import Settings

USER = "usr_" + "a" * 32
SAVED_ID = "b66skill_" + "c" * 32

UPSTREAM_CLASS_HEADER = "X-B66-Upstream-Class"
ALLOWLISTED_CLASSES = (
    "upstream_timeout",
    "upstream_busy",
    "upstream_response_too_large",
    "malformed_upstream",
    "upstream_unavailable",
    "provider_auth_error",
    "provider_route_error",
    "provider_server_error",
    "upstream_execution_failed",
    "upstream_error",
)


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.example.test",
        session_secret="b66-upstream-class-diagnostics-session-secret-not-real",
        session_max_age_seconds=3600,
        live_enabled="false",
    )


def _skill() -> dict:
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


class _Store:
    def get_skill(self, *, user_id, workspace_id, saved_skill_id):
        if saved_skill_id != SAVED_ID or user_id != USER:
            return None
        return {
            "saved_skill_id": SAVED_ID,
            "skill_id": "saved-skill-1",
            "skill_name": "우리 견적서",
            "skill_fingerprint": "d" * 64,
            "skill_version": 1,
            "skill": _skill(),
        }


class _RaisingClient:
    """Client whose single model call fails with the given exception."""

    def __init__(self, exc: BaseException):
        self.exc = exc
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


class _AnswerClient:
    """Client returning a fixed provider payload (bounded-error control case)."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        return {"answer": self.answer}


def _client(interpreter) -> TestClient:
    app = create_app(
        settings=_settings(),
        history_store=MagicMock(),
        b66_saved_quote_skill_store=_Store(),
        b66_quote_interpreter=interpreter,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), USER),
        domain="chat.example.test",
        path="/",
    )
    return client


def _post(client: TestClient, message: str = "견적 입력 진단"):
    return client.post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID, "message": message},
    )


def _upstream_class_values(response) -> list[str]:
    return [value for name, value in response.headers.items() if name.lower() == UPSTREAM_CLASS_HEADER.lower()]


def _assert_no_values_leak(response, *forbidden: str) -> None:
    body = response.text
    for name, value in response.headers.items():
        for needle in forbidden:
            assert needle not in value, f"header {name} leaked a value"
            assert needle not in body, f"body leaked a value via {name}"


def test_allowlisted_upstream_classes_are_relayed_exactly_once():
    for code in ALLOWLISTED_CLASSES:
        provider = _RaisingClient(ChatRuntimeError(502, code, "bounded upstream diagnostic"))
        response = _post(_client(B66QuoteConversationInterpreter(provider)))

        # 공개 502 계약은 그대로다.
        assert response.status_code == 502
        body = response.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "quote_interpretation_failed"
        assert body["error"]["message"] == "견적 요청을 해석하지 못했습니다."

        # 허용된 upstream class 하나만 정확히 1개 전달된다.
        assert _upstream_class_values(response) == [code]
        assert UPSTREAM_CLASS_HEADER in response.headers
        assert not [name for name in response.headers if name.startswith("X-B66-Rejection-")]
        assert provider.calls == 1

    print("UPSTREAM_CLASS_ALLOWLIST_RELAY=PASS")
    print(f"UPSTREAM_CLASS_ALLOWLIST_SIZE={len(ALLOWLISTED_CLASSES)}")
    print("UPSTREAM_CLASS_HEADER_COUNT=1")


def test_non_allowlisted_chat_runtime_errors_carry_no_header():
    for code in ("model_profile_unassigned", "upstream_binding_unavailable", "invalid_request"):
        provider = _RaisingClient(ChatRuntimeError(503, code, "bounded upstream diagnostic"))
        response = _post(_client(B66QuoteConversationInterpreter(provider)))

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "quote_interpretation_failed"
        assert UPSTREAM_CLASS_HEADER not in response.headers
        assert provider.calls == 1

    print("NON_ALLOWLISTED_CLASS_HEADER_ABSENT=PASS")


def test_generic_runtime_error_carries_no_upstream_class_header():
    provider = _RaisingClient(RuntimeError("engine lane unavailable 대한테스트건설"))
    response = _post(_client(B66QuoteConversationInterpreter(provider)))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "quote_interpretation_failed"
    assert UPSTREAM_CLASS_HEADER not in response.headers
    _assert_no_values_leak(response, "engine lane unavailable", "대한테스트건설")
    assert provider.calls == 1

    print("GENERIC_EXCEPTION_HEADER_ABSENT=PASS")


def test_upstream_class_header_never_leaks_exception_text_or_customer_values():
    raw_message = (
        "provider rejected 대한테스트건설 배관 100 미터, unitPrice=18000 "
        "at https://engine.internal/private?token=must-not-appear"
    )
    provider = _RaisingClient(ChatRuntimeError(502, "upstream_timeout", raw_message))
    response = _post(_client(B66QuoteConversationInterpreter(provider)), "대한테스트건설에 배관 100미터")

    assert response.status_code == 502
    assert response.headers[UPSTREAM_CLASS_HEADER] == "upstream_timeout"
    _assert_no_values_leak(
        response,
        "provider rejected",
        "대한테스트건설",
        "배관",
        "18000",
        "engine.internal",
        "must-not-appear",
    )
    assert provider.calls == 1

    print("UPSTREAM_CLASS_VALUE_IS_ALLOWLISTED_LABEL_ONLY=YES")
    print("RAW_EXCEPTION_TEXT_EXPOSED=NO")
    print("CUSTOMER_VALUE_EXPOSED=NO")


def test_bounded_rejection_contract_is_unchanged_for_model_errors():
    provider = _AnswerClient(json.dumps({"recipient": {"company": "대한테스트건설"}}, ensure_ascii=False))
    response = _post(_client(B66QuoteConversationInterpreter(provider)), "대한테스트건설 견적")

    # 이 payload 는 items/수량이 없어도 정상 후보이므로 200 이어야 한다.
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert UPSTREAM_CLASS_HEADER not in response.headers

    broken = _AnswerClient(5)
    rejected = _post(_client(B66QuoteConversationInterpreter(broken)), "대한테스트건설 견적")
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "quote_input_unrecognized"
    assert UPSTREAM_CLASS_HEADER not in rejected.headers

    print("BOUNDED_REJECTION_CONTRACT=UNCHANGED")
    print("UPSTREAM_CLASS_HEADER_NOT_ON_422=PASS")
