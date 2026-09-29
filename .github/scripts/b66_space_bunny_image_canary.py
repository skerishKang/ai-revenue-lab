"""One-shot B66 Space Bunny image canary (#3212).

Source-safe by default: importing or running without --authorized-live-run makes
no network call. The live path sends exactly one synthetic F02 quotation image
through the exact manual Space Bunny route, with retry=0 and fallback=0, and
checks actual visual facts without printing prompt/image/response content.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

B14_BASE_URL = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev"
HEALTH_PATH = "/api/pilot/health"
MODELS_PATH = "/api/pilot/models"
CHAT_PATH = "/api/pilot/v1/chat/completions"

MODEL_ID = "kilo/stealth-space-bunny-alpha"
UPSTREAM_MODEL = "stealth/space-bunny-alpha"
PROVIDER_ID = "kilo"
PROVIDER_NAME = "Kilo Gateway / Stealth"

MAX_PROVIDER_CALLS = 1
RETRY = 0
FALLBACK = 0
REQUEST_TIMEOUT_SECONDS = 45
MAX_RESPONSE_BYTES = 256 * 1024

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    ROOT
    / "packages"
    / "padiem-ai-core"
    / "tests"
    / "fixtures"
    / "b66_e2e_corpus"
    / "f02-scanned-quotation.png"
)
FIXTURE_SHA256 = "af9f48578b79dc9d712e695079e4b0fd44a02916f12007c14429593173432ba4"

EXPECTED = {
    "quote_number": "Q-2026-3002",
    "recipient": "주식회사 샘플산업",
    "first_item": "스테인리스 배관 40x40",
    "first_quantity": "12",
    "first_unit_price": "9800",
}

PROMPT = (
    "이 합성 한국어 견적서 이미지에서 실제로 보이는 값만 읽으세요. "
    "반드시 JSON 객체 하나만 반환하고 마크다운이나 설명을 붙이지 마세요. "
    "키는 quote_number, recipient, first_item, first_quantity, first_unit_price만 사용하세요. "
    "읽을 수 없는 값은 JSON null로 두세요. 합계나 부가세를 계산하지 마세요."
)

Transport = Callable[[str, str, dict[str, Any] | None], tuple[int, bytes]]


def _bounded_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("response_too_large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed_response") from exc
    if not isinstance(payload, dict):
        raise ValueError("malformed_response")
    return payload


def _request(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, bytes]:
    payload = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "padiem-b66-space-bunny-image-canary/1.0",
    }
    if body is not None:
        payload = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        B14_BASE_URL + path, data=payload, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            return int(response.status), raw
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(MAX_RESPONSE_BYTES + 1)


def _fixture_bytes() -> bytes:
    raw = FIXTURE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError("fixture_hash_mismatch")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("fixture_not_png")
    return raw


def canonical_chat_body(image: bytes) -> dict[str, Any]:
    data_url = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    return {
        "model": MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "stream": False,
        "business14": {
            "required_capabilities": ["image"],
            "allow_external_fallback": False,
            "max_attempts": 1,
        },
    }


def _assistant_json(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("invalid_choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("invalid_choices")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("invalid_message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty_answer")
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("answer_not_json") from exc
    if not isinstance(result, dict):
        raise ValueError("answer_not_object")
    return result


def _compact_number(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return None
        return str(int(value))
    if not isinstance(value, str):
        return None
    compact = value.replace(",", "").replace(" ", "").strip()
    return compact if compact.isdigit() else None


def _visual_facts_match(result: dict[str, Any]) -> bool:
    if result.get("quote_number") != EXPECTED["quote_number"]:
        return False
    if result.get("recipient") != EXPECTED["recipient"]:
        return False
    if result.get("first_item") != EXPECTED["first_item"]:
        return False
    if _compact_number(result.get("first_quantity")) != EXPECTED["first_quantity"]:
        return False
    if _compact_number(result.get("first_unit_price")) != EXPECTED["first_unit_price"]:
        return False
    return True


def _safe_error_code(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        return "unknown"
    code = error.get("code")
    allowed = {
        "invalid_body",
        "no_safe_route",
        "provider_timeout",
        "provider_bad_response",
        "provider_server_error",
        "provider_auth_error",
        "provider_rate_limited",
        "provider_error",
    }
    return code if isinstance(code, str) and code in allowed else "unknown"


def _locks(posts: int) -> None:
    print(f"B14_CHAT_POST_COUNT={posts}")
    print("NETWORK_RETRY_COUNT=0")
    print("MAX_PROVIDER_CALLS=1")
    print("RETRY=0")
    print("FALLBACK=0")
    print("RAW_RESPONSE_CONTENT_OUTPUT=0")
    print("PRIVATE_PAYLOAD_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")


def run(*, transport: Transport, authorized: bool) -> int:
    if not authorized:
        print("B66_SPACE_BUNNY_IMAGE_CANARY=BLOCKED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        _locks(0)
        return 2

    try:
        image = _fixture_bytes()
    except (OSError, ValueError) as exc:
        print(f"B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_{exc}")
        _locks(0)
        return 3

    health_status, health_raw = transport("GET", HEALTH_PATH, None)
    if health_status != 200:
        print(f"B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_HEALTH_HTTP_{health_status}")
        _locks(0)
        return 4
    try:
        health = _bounded_json(health_raw)
    except ValueError as exc:
        print(f"B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_HEALTH_{exc}")
        _locks(0)
        return 4
    b14 = health.get("business14")
    if not isinstance(b14, dict) or b14.get("provider_mode") != "live":
        print("B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_PROVIDER_MODE")
        _locks(0)
        return 4

    models_status, models_raw = transport("GET", MODELS_PATH, None)
    if models_status != 200:
        print(f"B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_MODELS_HTTP_{models_status}")
        _locks(0)
        return 5
    try:
        models = _bounded_json(models_raw)
    except ValueError as exc:
        print(f"B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_MODELS_{exc}")
        _locks(0)
        return 5

    routes = models.get("registered_routes")
    route = next(
        (
            item
            for item in routes or []
            if isinstance(item, dict) and item.get("id") == MODEL_ID
        ),
        None,
    )
    if not isinstance(route, dict):
        print("B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_ROUTE_NOT_REGISTERED")
        _locks(0)
        return 5
    if (
        route.get("provider_id") != PROVIDER_ID
        or route.get("upstream_model") != UPSTREAM_MODEL
        or route.get("explicit_only") is not True
    ):
        print("B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_ROUTE_IDENTITY")
        _locks(0)
        return 5

    catalog = models.get("catalog")
    catalog_entry = next(
        (
            item
            for item in catalog or []
            if isinstance(item, dict) and item.get("id") == MODEL_ID
        ),
        None,
    )
    if not isinstance(catalog_entry, dict) or "image" not in (catalog_entry.get("tags") or []):
        print("B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_IMAGE_CAPABILITY")
        _locks(0)
        return 5

    posts = 1
    status, raw = transport("POST", CHAT_PATH, canonical_chat_body(image))
    if status != 200:
        try:
            code = _safe_error_code(_bounded_json(raw))
        except ValueError:
            code = "unknown"
        print(f"B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_CHAT_{status}_{code}")
        _locks(posts)
        return 6

    try:
        payload = _bounded_json(raw)
        facts = _assistant_json(payload)
    except ValueError as exc:
        print(f"B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_{exc}")
        _locks(posts)
        return 6

    meta = payload.get("business14")
    if not isinstance(meta, dict):
        print("B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_B14_META")
        _locks(posts)
        return 6

    checks = {
        "selected_model": meta.get("selected_model") == MODEL_ID,
        "selected_upstream_model": meta.get("selected_upstream_model") == UPSTREAM_MODEL,
        "selected_provider": meta.get("selected_provider") == PROVIDER_NAME,
        "route_mode": meta.get("route_mode") == "manual",
        "fallback_allowed": meta.get("fallback_allowed") is False,
        "fallback_used": meta.get("fallback_used") is False,
        "attempt_count": meta.get("attempt_count") == 1,
        "route_evidence_status": meta.get("route_evidence_status") == "live_verified",
        "actual_response_model": meta.get("actual_response_model") == UPSTREAM_MODEL,
    }
    failed = sorted(key for key, ok in checks.items() if not ok)
    if failed:
        print("B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_ROUTE_EVIDENCE")
        print("FAILED_ROUTE_CHECKS=" + ",".join(failed))
        _locks(posts)
        return 6

    if not _visual_facts_match(facts):
        print("B66_SPACE_BUNNY_IMAGE_CANARY=FAIL_VISUAL_FACTS")
        _locks(posts)
        return 7

    print("B66_SPACE_BUNNY_IMAGE_CANARY=PASS")
    print("EXACT_MODEL_ROUTE=PASS")
    print("IMAGE_CAPABILITY=PASS")
    print("ACTUAL_RESPONSE_MODEL_EVIDENCE=PASS")
    print("FALLBACK_USED=NO")
    print("ATTEMPT_COUNT=1")
    print("F02_VISUAL_FACTS=PASS")
    _locks(posts)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    authorized = args == ["--authorized-live-run"]
    return run(transport=_request, authorized=authorized)


if __name__ == "__main__":
    raise SystemExit(main())
