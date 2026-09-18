from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b14_agnes_production_smoke.py"

spec = importlib.util.spec_from_file_location("b14_agnes_production_smoke", SCRIPT)
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def _json(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _health(*, has_key: bool = True) -> bytes:
    return _json(
        {
            "status": "ok",
            "business14": {
                "provider_mode": "live",
                "providers": [
                    {"id": "agnes-ai", "registered": True, "has_key": has_key}
                ],
            },
        }
    )


def _models() -> bytes:
    return _json(
        {
            "registered_routes": [
                {
                    "id": smoke.MODEL_ID,
                    "provider_id": smoke.PROVIDER_ID,
                    "upstream_model": smoke.UPSTREAM_MODEL,
                }
            ]
        }
    )


def _chat() -> bytes:
    return _json(
        {
            "id": "synthetic",
            "object": "chat.completion",
            "model": smoke.UPSTREAM_MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "business14": {
                "mode": "live",
                "provider_mode": "live",
                "provider": smoke.PROVIDER_NAME,
                "selected_provider": smoke.PROVIDER_NAME,
                "model_route": smoke.MODEL_ID,
                "selected_model": smoke.MODEL_ID,
                "upstream_model": smoke.UPSTREAM_MODEL,
                "selected_upstream_model": smoke.UPSTREAM_MODEL,
                "actual_response_model": smoke.UPSTREAM_MODEL,
                "route_mode": "manual",
                "fallback_used": False,
                "attempt_count": 1,
                "route_evidence_status": "live_verified",
            },
        }
    )


def test_fixed_contract_is_exact_agnes_manual_route() -> None:
    assert smoke.MODEL_ID == "agnes-ai/agnes-3.0-flash"
    assert smoke.UPSTREAM_MODEL == "agnes-3.0-flash"
    assert smoke.PROVIDER_ID == "agnes-ai"
    assert smoke.PROVIDER_NAME == "Agnes AI"
    assert smoke.canonical_chat_body() == {
        "model": "agnes-ai/agnes-3.0-flash",
        "messages": [
            {
                "role": "user",
                "content": "Production route smoke. Reply with the single word OK.",
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
    }


def test_success_uses_two_gets_and_exactly_one_chat_post() -> None:
    calls: list[tuple[str, str, dict | None]] = []

    def transport(method: str, path: str, body: dict | None):
        calls.append((method, path, body))
        if path == smoke.HEALTH_PATH:
            return 200, _health()
        if path == smoke.MODELS_PATH:
            return 200, _models()
        if path == smoke.CHAT_PATH:
            return 200, _chat()
        raise AssertionError(path)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    assert rc == 0
    assert [(m, p) for m, p, _ in calls] == [
        ("GET", smoke.HEALTH_PATH),
        ("GET", smoke.MODELS_PATH),
        ("POST", smoke.CHAT_PATH),
    ]
    output = stdout.getvalue()
    assert "AGNES_PRODUCTION_SMOKE=PASS" in output
    assert "AGNES_ATTEMPT_COUNT=1" in output
    assert "B14_CHAT_POST_COUNT=1" in output
    assert "NETWORK_RETRY_COUNT=0" in output
    assert "RAW_RESPONSE_CONTENT_OUTPUT=0" in output
    assert "SECRET_VALUE_OUTPUT=0" in output
    assert "OK" not in output


def test_missing_credential_fails_before_chat_post() -> None:
    calls: list[tuple[str, str]] = []

    def transport(method: str, path: str, body: dict | None):
        calls.append((method, path))
        if path == smoke.HEALTH_PATH:
            return 200, _health(has_key=False)
        raise AssertionError("must fail before models/chat")

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    assert rc == 1
    assert calls == [("GET", smoke.HEALTH_PATH)]
    assert "FAIL_CREDENTIAL_NOT_READY" in stdout.getvalue()
    assert "B14_CHAT_POST_COUNT=0" in stdout.getvalue()


def test_wrong_route_fails_before_provider_post() -> None:
    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health()
        if path == smoke.MODELS_PATH:
            return 200, _json(
                {
                    "registered_routes": [
                        {
                            "id": smoke.MODEL_ID,
                            "provider_id": "wrong-provider",
                            "upstream_model": smoke.UPSTREAM_MODEL,
                        }
                    ]
                }
            )
        raise AssertionError("must fail before chat")

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    assert rc == 1
    assert "FAIL_ROUTE_IDENTITY" in stdout.getvalue()
    assert "B14_CHAT_POST_COUNT=0" in stdout.getvalue()


def test_non_200_chat_emits_only_safe_error_code() -> None:
    raw_secret = "sensitive-provider-detail"

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health()
        if path == smoke.MODELS_PATH:
            return 200, _models()
        if path == smoke.CHAT_PATH:
            return 503, _json(
                {
                    "error": {
                        "code": "no_safe_route",
                        "message": raw_secret,
                    }
                }
            )
        raise AssertionError(path)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    output = stdout.getvalue()
    assert rc == 1
    assert "FAIL_CHAT_HTTP_503" in output
    assert "ENGINE_ERROR_CODE=no_safe_route" in output
    assert raw_secret not in output
    assert "B14_CHAT_POST_COUNT=1" in output
    assert "NETWORK_RETRY_COUNT=0" in output


def test_success_requires_exact_live_agnes_metadata_and_one_attempt() -> None:
    payload = json.loads(_chat().decode("utf-8"))
    payload["business14"]["attempt_count"] = 2
    payload["business14"]["fallback_used"] = True
    payload["business14"]["actual_response_model"] = "other-model"

    def transport(method: str, path: str, body: dict | None):
        if path == smoke.HEALTH_PATH:
            return 200, _health()
        if path == smoke.MODELS_PATH:
            return 200, _models()
        return 200, _json(payload)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = smoke.run(transport=transport)

    output = stdout.getvalue()
    assert rc == 1
    assert "AGNES_PRODUCTION_SMOKE=FAIL_ROUTE_METADATA" in output
    assert "actual_response_model" in output
    assert "attempt_count" in output
    assert "fallback_used" in output
    assert "B14_CHAT_POST_COUNT=1" in output
