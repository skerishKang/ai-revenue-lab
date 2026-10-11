from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any, Callable


B14_BASE_URL = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev"
HEALTH_PATH = "/api/pilot/health"
MODELS_PATH = "/api/pilot/models"
CHAT_PATH = "/api/pilot/v1/chat/completions"

MODEL_ID = "agnes-ai/agnes-3.0-flash"
PROVIDER_ID = "agnes-ai"
PROVIDER_NAME = "Agnes AI"
UPSTREAM_MODEL = "agnes-3.0-flash"
REQUEST_TIMEOUT_SECONDS = 75
MAX_RESPONSE_BYTES = 1_048_576

HttpTransport = Callable[[str, str, dict[str, Any] | None], tuple[int, bytes]]


def _bounded_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("response_too_large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ValueError("response_not_object")
    return value


def _request(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, bytes]:
    payload = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "padiem-b14-agnes-production-smoke/1.0",
    }
    if body is not None:
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{B14_BASE_URL}{path}",
        data=payload,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            return response.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(MAX_RESPONSE_BYTES + 1)


def canonical_chat_body() -> dict[str, Any]:
    return {
        "model": MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": "Production route smoke. Reply with the single word OK.",
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
    }


def _safe_error_code(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        return "unknown"
    code = error.get("code")
    return code if isinstance(code, str) and 1 <= len(code) <= 96 else "unknown"


def run(transport: HttpTransport = _request) -> int:
    provider_posts = 0
    network_retries = 0

    health_status, health_raw = transport("GET", HEALTH_PATH, None)
    if health_status != 200:
        print(f"AGNES_PRODUCTION_SMOKE=FAIL_HEALTH_HTTP_{health_status}")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1
    try:
        health = _bounded_json(health_raw)
    except ValueError as exc:
        print(f"AGNES_PRODUCTION_SMOKE=FAIL_HEALTH_{exc}")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    business14 = health.get("business14")
    if not isinstance(business14, dict) or business14.get("provider_mode") != "live":
        print("AGNES_PRODUCTION_SMOKE=FAIL_PROVIDER_MODE")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    providers = business14.get("providers")
    if not isinstance(providers, list):
        print("AGNES_PRODUCTION_SMOKE=FAIL_PROVIDER_LIST")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1
    agnes_provider = next(
        (
            item
            for item in providers
            if isinstance(item, dict) and item.get("id") == PROVIDER_ID
        ),
        None,
    )
    if not isinstance(agnes_provider, dict) or agnes_provider.get("registered") is not True:
        print("AGNES_PRODUCTION_SMOKE=FAIL_PROVIDER_NOT_REGISTERED")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1
    if agnes_provider.get("has_key") is not True:
        print("AGNES_PRODUCTION_SMOKE=FAIL_CREDENTIAL_NOT_READY")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1
    print("AGNES_PROVIDER_REGISTERED=YES")
    print("AGNES_CREDENTIAL_READY=YES")

    models_status, models_raw = transport("GET", MODELS_PATH, None)
    if models_status != 200:
        print(f"AGNES_PRODUCTION_SMOKE=FAIL_MODELS_HTTP_{models_status}")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1
    try:
        models = _bounded_json(models_raw)
    except ValueError as exc:
        print(f"AGNES_PRODUCTION_SMOKE=FAIL_MODELS_{exc}")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    routes = models.get("registered_routes")
    if not isinstance(routes, list):
        print("AGNES_PRODUCTION_SMOKE=FAIL_ROUTE_LIST")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1
    route = next(
        (
            item
            for item in routes
            if isinstance(item, dict) and item.get("id") == MODEL_ID
        ),
        None,
    )
    if not isinstance(route, dict):
        print("AGNES_PRODUCTION_SMOKE=FAIL_ROUTE_NOT_REGISTERED")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1
    if route.get("provider_id") != PROVIDER_ID or route.get("upstream_model") != UPSTREAM_MODEL:
        print("AGNES_PRODUCTION_SMOKE=FAIL_ROUTE_IDENTITY")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1
    print("AGNES_ROUTE_REGISTERED=YES")

    provider_posts += 1
    chat_status, chat_raw = transport("POST", CHAT_PATH, canonical_chat_body())
    if chat_status != 200:
        try:
            payload = _bounded_json(chat_raw)
            error_code = _safe_error_code(payload)
        except ValueError:
            error_code = "unparseable"
        print(f"AGNES_PRODUCTION_SMOKE=FAIL_CHAT_HTTP_{chat_status}")
        print(f"ENGINE_ERROR_CODE={error_code}")
        print(f"B14_CHAT_POST_COUNT={provider_posts}")
        print(f"NETWORK_RETRY_COUNT={network_retries}")
        return 1

    try:
        chat = _bounded_json(chat_raw)
    except ValueError as exc:
        print(f"AGNES_PRODUCTION_SMOKE=FAIL_CHAT_{exc}")
        print(f"B14_CHAT_POST_COUNT={provider_posts}")
        print(f"NETWORK_RETRY_COUNT={network_retries}")
        return 1

    meta = chat.get("business14")
    if not isinstance(meta, dict):
        print("AGNES_PRODUCTION_SMOKE=FAIL_METADATA_MISSING")
        print(f"B14_CHAT_POST_COUNT={provider_posts}")
        print(f"NETWORK_RETRY_COUNT={network_retries}")
        return 1

    checks = {
        "mode": meta.get("mode") == "live",
        "provider_mode": meta.get("provider_mode") == "live",
        "provider": meta.get("provider") == PROVIDER_NAME,
        "selected_provider": meta.get("selected_provider") == PROVIDER_NAME,
        "model_route": meta.get("model_route") == MODEL_ID,
        "selected_model": meta.get("selected_model") == MODEL_ID,
        "upstream_model": meta.get("upstream_model") == UPSTREAM_MODEL,
        "selected_upstream_model": meta.get("selected_upstream_model") == UPSTREAM_MODEL,
        "actual_response_model": meta.get("actual_response_model") == UPSTREAM_MODEL,
        "route_mode": meta.get("route_mode") == "manual",
        "fallback_used": meta.get("fallback_used") is False,
        "attempt_count": meta.get("attempt_count") == 1,
        "route_evidence_status": meta.get("route_evidence_status") == "live_verified",
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        print("AGNES_PRODUCTION_SMOKE=FAIL_ROUTE_METADATA")
        print("FAILED_METADATA_CHECKS=" + ",".join(sorted(failed)))
        print(f"B14_CHAT_POST_COUNT={provider_posts}")
        print(f"NETWORK_RETRY_COUNT={network_retries}")
        return 1

    choices = chat.get("choices")
    if (
        not isinstance(choices, list)
        or not choices
        or not isinstance(choices[0], dict)
        or not isinstance(choices[0].get("message"), dict)
        or not isinstance(choices[0]["message"].get("content"), str)
        or not choices[0]["message"]["content"].strip()
    ):
        print("AGNES_PRODUCTION_SMOKE=FAIL_EMPTY_ANSWER")
        print(f"B14_CHAT_POST_COUNT={provider_posts}")
        print(f"NETWORK_RETRY_COUNT={network_retries}")
        return 1

    print("AGNES_PRODUCTION_SMOKE=PASS")
    print(f"AGNES_MODEL_ROUTE={MODEL_ID}")
    print(f"AGNES_UPSTREAM_MODEL={UPSTREAM_MODEL}")
    print("AGNES_ACTUAL_RESPONSE_MODEL_MATCH=YES")
    print("AGNES_PROVIDER_MATCH=YES")
    print("AGNES_FALLBACK_USED=NO")
    print("AGNES_ATTEMPT_COUNT=1")
    print(f"B14_CHAT_POST_COUNT={provider_posts}")
    print(f"NETWORK_RETRY_COUNT={network_retries}")
    print("RAW_RESPONSE_CONTENT_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    sys.exit(run())
