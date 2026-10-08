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

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b14_client import ChatRuntimeError
from app.b66_quote_conversation import B66QuoteConversationInterpreter
from app.config import Settings
from app.dispatch_quota import DispatchAwareB14Client
from app.model_policy import (
    DEFAULT_B14_MODEL_ID,
    EXECUTABLE_B14_MODEL_IDS,
    model_policy_is_executable,
    resolve_request_model_policy,
)

USER = "usr_" + "a" * 32
SAVED_ID = "b66skill_" + "c" * 32

UPSTREAM_CLASS_HEADER = "X-B66-Upstream-Class"
ALLOWLISTED_CLASSES = (
    "upstream_timeout",
    "upstream_busy",
    "upstream_response_too_large",
    "malformed_upstream",
    "upstream_malformed_json",
    "upstream_unexpected_shape",
    "upstream_missing_content",
    "upstream_non_text_content",
    "upstream_empty_answer",
    "upstream_unavailable",
    "provider_auth_error",
    "provider_route_error",
    "provider_server_error",
    "upstream_execution_failed",
    "upstream_error",
    # Raised by the Production-composed DispatchAwareB14Client itself when the
    # required B14 Service Binding is absent (worker.py composition).
    "upstream_binding_unavailable",
)

# Stable product-owned ChatRuntimeError codes that stay OUT of the
# ``X-B66-Upstream-Class`` allowlist. Each entry records the status the code
# actually carries and why it is not an upstream class on this lane.
EXCLUDED_CLASSES = (
    # In real Production B62 Plus is HOLD; this synthetic diagnostic fixture
    # is not proof that model_profile_unassigned is unreachable from B66.
    (503, "model_profile_unassigned"),
    # Reachable only when the quote text itself begins with a slash alias; these
    # are product policy rejections, not upstream failures.
    (422, "tier_unavailable"),
    (422, "unknown_model_alias"),
    (422, "model_alias_requires_prompt"),
    # Core request-contract rejection, not a provider/upstream class.
    (422, "invalid_request"),
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


def _production_settings() -> Settings:
    """Same flags as the worker.py composition: runtime_mode b14 + live armed."""

    return Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.internal",
        auth_mode="password",
        public_base_url="https://chat.example.test",
        session_secret="b66-upstream-class-diagnostics-session-secret-not-real",
        session_max_age_seconds=3600,
        live_enabled="true",
    )


def _unbound_production_client() -> DispatchAwareB14Client:
    """The Production-composed client with the B14 Service Binding absent.

    worker.py composes ``require_service_binding=settings.runtime_mode == "b14"``
    and leaves ``service_transport`` None when the binding is missing, so this is
    the real pre-dispatch shape, not a simulated raise. No provider call happens.
    """

    return DispatchAwareB14Client(
        _production_settings(),
        service_transport=None,
        require_service_binding=True,
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


@pytest.mark.parametrize(
    "diagnostic_class",
    [
        "upstream_malformed_json",
        "upstream_unexpected_shape",
        "upstream_missing_content",
        "upstream_non_text_content",
        "upstream_empty_answer",
    ],
)
def test_bounded_malformed_detail_overrides_public_chat_code_for_header_only(
    diagnostic_class: str,
):
    provider = _RaisingClient(
        ChatRuntimeError(
            502,
            "malformed_upstream",
            "bounded upstream diagnostic",
            upstream_class=diagnostic_class,
        )
    )
    response = _post(_client(B66QuoteConversationInterpreter(provider)))

    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "quote_interpretation_failed"
    assert body["error"]["message"] == "견적 요청을 해석하지 못했습니다."
    assert _upstream_class_values(response) == [diagnostic_class]
    assert "malformed_upstream" not in _upstream_class_values(response)
    assert provider.calls == 1


def test_non_allowlisted_chat_runtime_errors_carry_no_header():
    for status, code in EXCLUDED_CLASSES:
        provider = _RaisingClient(ChatRuntimeError(status, code, "bounded upstream diagnostic"))
        response = _post(_client(B66QuoteConversationInterpreter(provider)))

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "quote_interpretation_failed"
        assert UPSTREAM_CLASS_HEADER not in response.headers
        assert provider.calls == 1

    print("NON_ALLOWLISTED_CLASS_HEADER_ABSENT=PASS")
    print(f"EXCLUDED_CLASS_COUNT={len(EXCLUDED_CLASSES)}")


def test_binding_class_is_reachable_from_the_production_composed_client():
    """Reachability proof for ``upstream_binding_unavailable`` on this lane.

    This drives the real Production-composed client (not a fake raising client),
    so a header value is backed by a path the deployment can actually take.
    """

    message = "대한건설에 배관 100미터, 부가세 별도"

    async def scenario():
        client = _unbound_production_client()
        with pytest.raises(ChatRuntimeError) as info:
            await client.complete(
                [{"role": "user", "content": message}],
                additional_system_context="견적 입력값 추출 계약",
                attachments=(),
            )
        return info.value

    error = asyncio.run(scenario())
    assert error.code == "upstream_binding_unavailable"
    assert error.status_code == 503
    assert error.code in ALLOWLISTED_CLASSES

    # Synthetic Plus fixture in conftest permits this binding-path test.
    # Real HOLD is proved separately by test_unassigned_profile_gate.py.
    assert resolve_request_model_policy([{"role": "user", "content": message}]).model_id == (
        DEFAULT_B14_MODEL_ID
    )
    assert model_policy_is_executable(DEFAULT_B14_MODEL_ID) is True
    assert DEFAULT_B14_MODEL_ID in EXECUTABLE_B14_MODEL_IDS

    print("UPSTREAM_BINDING_UNAVAILABLE_REACHABLE_FROM_PRODUCTION_COMPOSITION=YES")
    print("B66_SYNTHETIC_PLUS_FIXTURE_ONLY=YES")


def test_real_binding_class_reaches_the_route_as_one_bounded_header():
    """End-to-end: the real unbound Production client -> route -> one header."""

    interpreter = B66QuoteConversationInterpreter(_unbound_production_client())
    response = _post(_client(interpreter))

    assert response.status_code == 502
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "quote_interpretation_failed"
    assert body["error"]["message"] == "견적 요청을 해석하지 못했습니다."
    assert _upstream_class_values(response) == ["upstream_binding_unavailable"]
    assert not [name for name in response.headers if name.startswith("X-B66-Rejection-")]

    print("REAL_BINDING_CLASS_HEADER_RELAY=PASS")


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


def test_502_interpreter_exception_provenance_is_bounded_without_raw_values():
    # One fake backend completion per trial, no network/provider runtime.
    failure_cases = (
        (TypeError("private company alpha; token=secret"), "type_error"),
        (ValueError("private company beta; token=secret"), "value_error"),
        (RuntimeError("private company gamma; token=secret"), "runtime_error"),
        (KeyError("private company delta; token=secret"), "unexpected_exception"),
        (ChatRuntimeError(422, "invalid_request", "private user message"),
         "chat_runtime_non_upstream"),
    )
    for exception, family in failure_cases:
        provider = _RaisingClient(exception)
        response = _post(_client(B66QuoteConversationInterpreter(provider)))
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "quote_interpretation_failed"
        assert response.headers["X-B66-Interpret-Failure-Stage"] == "interpreter_exception"
        assert response.headers["X-B66-Interpret-Exception-Family"] == family
        assert UPSTREAM_CLASS_HEADER not in response.headers
        _assert_no_values_leak(
            response, "private company", "token=secret", "user message"
        )
        assert provider.calls == 1
    print("B66_502_EXCEPTION_FAMILIES_ENUM_ONLY=PASS")


def test_502_allowlisted_upstream_stage_keeps_existing_single_header():
    provider = _RaisingClient(ChatRuntimeError(
        502, "upstream_timeout", "private quote content"
    ))
    response = _post(_client(B66QuoteConversationInterpreter(provider)))
    assert response.status_code == 502
    assert response.headers[UPSTREAM_CLASS_HEADER] == "upstream_timeout"
    assert response.headers["X-B66-Interpret-Failure-Stage"] == "interpreter_exception"
    assert "X-B66-Interpret-Exception-Family" not in response.headers
    _assert_no_values_leak(response, "private quote content")


def test_502_invalid_projection_has_distinct_stage_no_exception_family():
    class InvalidProjection:
        async def interpret(self, *, message, skill):
            return {"internal_message": "DO_NOT_RELAY_PRIVATE_CONTENT"}

    response = _post(_client(InvalidProjection()))
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "quote_interpretation_failed"
    assert response.headers["X-B66-Interpret-Failure-Stage"] == "projection_missing_safe_dict"
    assert "X-B66-Interpret-Exception-Family" not in response.headers
    assert UPSTREAM_CLASS_HEADER not in response.headers
    _assert_no_values_leak(response, "DO_NOT_RELAY_PRIVATE_CONTENT")


def test_422_rejection_does_not_claim_502_provenance():
    provider = _AnswerClient(5)
    response = _post(_client(B66QuoteConversationInterpreter(provider)))
    assert response.status_code == 422
    assert "X-B66-Interpret-Failure-Stage" not in response.headers
    assert "X-B66-Interpret-Exception-Family" not in response.headers
    assert UPSTREAM_CLASS_HEADER not in response.headers
