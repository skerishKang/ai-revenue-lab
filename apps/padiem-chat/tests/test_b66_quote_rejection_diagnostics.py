"""Focused regression (#3391): bounded rejection diagnostics on the B66
interpret route.

The public 422 contract is unchanged; the response may additionally carry
allowlisted X-B66-Rejection-* headers (reason / field path / JSON type name)
so Production can observe WHY normalize_conversation_output rejected a model
answer — without exposing the raw model answer or any customer value.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_quote_conversation import B66QuoteConversationInterpreter
from app.config import Settings

USER = "usr_" + "a" * 32
SAVED_ID = "b66skill_" + "c" * 32


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.example.test",
        session_secret="b66-rejection-diagnostics-session-secret-not-real",
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


class _AnswerClient:
    """One-model-call client returning a fixed provider answer."""

    def __init__(self, answer: dict):
        self.answer = answer
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        return {"answer": json.dumps(self.answer, ensure_ascii=False)}


class _RawAnswerClient:
    """One-model-call client returning an exact raw provider answer string."""

    def __init__(self, answer: str):
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


def _post(client: TestClient, message: str):
    return client.post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID, "message": message},
    )


def _assert_no_values_leak(response, *forbidden: str) -> None:
    """본문과 모든 헤더에서 고객/모델 값 문자열이 재등장하지 않는다는 계약."""
    body = response.text
    for name, value in response.headers.items():
        for needle in forbidden:
            assert needle not in value, f"header {name} leaked a value"
            assert needle not in body, f"body leaked a value via {name}"


def test_invalid_number_rejection_carries_bounded_path_headers():
    provider = _AnswerClient(
        {
            "recipient": {"company": "대한테스트건설"},
            "items": [
                {"name": "배관", "qty": 100, "unitPrice": 18000},
                {"name": "테스트 시공비", "qty": 2, "unitPrice": "18,000"},
            ],
            "taxMode": "EXCLUSIVE",
            "detailGroups": [],
        }
    )
    response = _post(_client(B66QuoteConversationInterpreter(provider)), "대한테스트건설에 배관 100미터, 부가세 별도")

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "quote_input_unrecognized"
    assert body["error"]["message"] == "견적 입력값을 확인해 주세요."

    assert response.headers["X-B66-Rejection-Reason"] == "invalid_number"
    # 필드 인덱스는 1-based 요약 순번 계약(summaryIndex)과 동일한 기준을 따른다.
    assert response.headers["X-B66-Rejection-Path"] == "items[2].unitPrice"
    assert response.headers["X-B66-Rejection-Type"] == "string"

    _assert_no_values_leak(response, "18,000", "대한테스트건설", "배관", "테스트 시공비")
    assert provider.calls == 1
    print("INVALID_NUMBER_REASON_HEADER=PASS")
    print("INVALID_NUMBER_PATH_HEADER=PASS")
    print("CUSTOMER_VALUE_EXPOSED=NO")


def test_unsupported_field_rejection_reports_top_level_only():
    interpreter = B66QuoteConversationInterpreter(
        _AnswerClient(
            {
                "amount": 5,
                "recipient": {"company": "대한테스트건설"},
                "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
            }
        )
    )
    response = _post(_client(interpreter), "대한테스트건설에 배관 100미터")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "quote_input_unrecognized"
    assert response.headers["X-B66-Rejection-Reason"] == "unsupported_output_field"
    assert response.headers["X-B66-Rejection-Path"] == "top_level"
    assert response.headers["X-B66-Rejection-Type"] == "object"

    # 알려지지 않은 필드 이름 자체는 어떤 헤더 값으로도 재노출되지 않는다.
    for name, value in response.headers.items():
        if name.startswith("X-B66-Rejection-"):
            assert "amount" not in value.lower()
    _assert_no_values_leak(response, "대한테스트건설", "배관")
    print("UNSUPPORTED_FIELD_REASON_HEADER=PASS")
    print("OFFENDING_KEY_NAME_NOT_EXPOSED=YES")


def test_non_string_recipient_reports_field_path_and_type():
    interpreter = B66QuoteConversationInterpreter(
        _AnswerClient(
            {
                "recipient": {"company": 123},
                "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
            }
        )
    )
    response = _post(_client(interpreter), "대한테스트건설에 배관 100미터")

    assert response.status_code == 422
    assert response.headers["X-B66-Rejection-Reason"] == "invalid_text"
    assert response.headers["X-B66-Rejection-Path"] == "recipient.company"
    assert response.headers["X-B66-Rejection-Type"] == "integer"
    _assert_no_values_leak(response, "배관")
    print("INVALID_TEXT_PATH_HEADER=PASS")


def test_generic_public_error_contract_unchanged_for_engine_failures():
    class ExplodingClient:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("engine lane unavailable")

    response = _post(
        _client(B66QuoteConversationInterpreter(ExplodingClient())),
        "대한테스트건설에 배관 100미터",
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "quote_interpretation_failed"
    # 엔진 레인 실패는 rejection 진단 헤더를 달지 않는다(해당 예외가 아니므로).
    assert "X-B66-Rejection-Reason" not in response.headers
    print("GENERIC_PUBLIC_ERROR_CONTRACT=UNCHANGED")
    print("RAW_ANSWER_EXPOSED=NO")

def test_invalid_model_output_reports_specific_bounded_answer_stage():
    cases = [
        ("", "answer.empty"),
        ("plain prose without a JSON object", "answer.no_json_object"),
        (
            "```json\\n{}\\n```\\n```json\\n{}\\n```",
            "answer.multiple_fences",
        ),
        ("```json\\n{bad json}\\n```", "answer.fenced_json_decode"),
        ('prefix {"recipient":', "answer.raw_json_decode"),
        (
            'prefix {"recipient": {}, "items": []} trailing { structural',
            "answer.unsafe_wrapper",
        ),
    ]

    for raw_answer, expected_path in cases:
        provider = _RawAnswerClient(raw_answer)
        response = _post(
            _client(B66QuoteConversationInterpreter(provider)),
            "bounded diagnostic input",
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "quote_input_unrecognized"
        assert response.headers["X-B66-Rejection-Reason"] == "invalid_model_output"
        assert response.headers["X-B66-Rejection-Path"] == expected_path
        assert response.headers["X-B66-Rejection-Type"] == "string"
        assert raw_answer not in response.text
        for name, value in response.headers.items():
            if name.lower().startswith("x-b66-rejection-"):
                assert raw_answer not in value
        assert provider.calls == 1

    print("INVALID_MODEL_OUTPUT_STAGE_DIAGNOSTICS=PASS")
    print("VALIDATION_ACCEPTANCE_CHANGED=NO")
