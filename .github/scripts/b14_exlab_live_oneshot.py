"""ExLab-only B14 one-shot live acceptance contract (#4516).

Separate, read-only, exactly-one-shot source contract for the single exact
model ``experiential/qwen3.8-flash-next-uncensored``.

Historical context (dated, not re-measured here): #4220 recorded a direct
ExLab same-upstream HTTP 200 (1750ms) while B14 attempts returned 429 and
504; #4252 recorded a B14 synthetic 429 (981ms, vendor
``route_unavailable`` = "Throttled, or no healthy route right now") and a
later B14 HTTP 200. Both are CLOSED. This gate proves nothing about live
reliability until a separately authorized run succeeds.

This module is deliberately inert: importing it, or invoking its default
entry point, never performs a live provider call. A live run requires an
explicitly supplied transport plus the one exact registered model id. It
never touches the Google-only gate, the generic candidate gate, member
tiers, or production routing.

Hard guarantees enforced here:

* exact-ID allowlist of exactly one model (no discovery, no AUTO lane)
* exact model identity (provider_id / model_id / upstream_model)
* expected credential binding **name** only, never a value
* ``MAX_PROVIDER_CALLS = 1``
* ``RETRY = 0`` (no network retry loop of any kind)
* ``FALLBACK = 0`` (a non-matching response is a failure, not a fallback)
* explicit ``business14={allow_external_fallback:false,max_attempts:1,
  max_retries:0}`` on the single chat POST
* text-only synthetic Korean prompt with no customer data
* bounded output tokens / timeout / response size (expense + rate cap)
* actual response provider/model evidence is required to match
* 429 vs 502/503/504/timeout classified into closed local classes; a 429 is
  NEVER attributed to a specific quota/key cause without vendor proof
* secret values and private prompt/response payload are never printed
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# The scripts directory is not a package, so make the canonical served-version
# resolver importable whether this module runs directly or is loaded through
# importlib in a test. This gate deliberately reuses the canonical resolver
# rather than reimplementing served-version rules.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cloudflare_served_version import (  # noqa: E402
    ServedVersionReason,
    ServedVersionResolutionError,
    resolve_served_version_id,
)

# --------------------------------------------------------------------------
# Shared transport / response bounds (same posture as the Gemini gate).
# --------------------------------------------------------------------------

B14_BASE_URL = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev"
HEALTH_PATH = "/api/pilot/health"
MODELS_PATH = "/api/pilot/models"
CHAT_PATH = "/api/pilot/v1/chat/completions"

REQUEST_TIMEOUT_SECONDS = 75
MAX_RESPONSE_BYTES = 1_048_576

# Bounded counters. These are contract constants, not tunables.
MAX_PROVIDER_CALLS = 1
RETRY = 0
FALLBACK = 0

# The AUTO lane must never back an ExLab live acceptance.
AUTO_MODEL_ID = "b14/auto"

# Output discipline markers pinned by the workflow source contract.
DEFAULT_LIVE_EXECUTION = "BLOCKED"
PRIVATE_PAYLOAD_OUTPUT = 0
SECRET_VALUE_OUTPUT = 0
PRODUCTION_MUTATION = 0
RAW_RESPONSE_CONTENT_OUTPUT = 0

# Provider protocol evidence (OpenAI-compatible ExLab origin).
PROVIDER_PROTOCOL = "OpenAI-compatible"
PROVIDER_CHAT_PATH = "v1/chat/completions"

HttpTransport = Callable[[str, str, "dict[str, Any] | None"], tuple[int, bytes]]


@dataclass(frozen=True)
class ExLabSpec:
    """The single explicitly allowlisted ExLab model.

    ``credential_binding`` is the **name** of the expected platform secret
    binding. Its value is never read, printed, or transmitted by this module.
    Callers never supply or override the credential.
    """

    model_id: str = "experiential/qwen3.8-flash-next-uncensored"
    evidence_prefix: str = "EXLAB_QWEN38"
    upstream_model: str = "qwen3.8-flash-next-uncensored"
    provider_id: str = "experiential"
    provider_name: str = "Experiential Labs"
    credential_binding: str = "PADIEM_B14_CREDENTIAL_04"
    expected_binding: str = "PADIEM_B14_CREDENTIAL_04"


# --------------------------------------------------------------------------
# Explicit exact-ID allowlist (#4516). Exactly one entry. No fallback
# assignment, no Google/Gemini ids, no generic candidate ids.
# --------------------------------------------------------------------------

EXLAB_MODEL_ID = "experiential/qwen3.8-flash-next-uncensored"

EXLAB_SPEC = ExLabSpec()

# Explicitly out of scope here. Absence from the allowlist is the
# enforcement; this tuple documents the boundary so a test can pin it.
EXLAB_EXCLUDED_MODEL_IDS: tuple[str, ...] = (
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.5-flash-lite",
    "opencode-go/muse-spark-1.3-contributor",
    "opencode-go/longcat-2.5-preview-free",
    "opencode-go/step-5-preview-free",
    "b-ai/qwen3.8-flash",
)


def resolve_exlab(model_id: str) -> ExLabSpec:
    """Resolve the one exact ExLab id or fail closed.

    An unknown id, an excluded id, or the AUTO lane marker raises
    ``ValueError``. There is no implicit default model.
    """

    if model_id == AUTO_MODEL_ID:
        raise ValueError("auto_route_not_permitted")
    if model_id in EXLAB_EXCLUDED_MODEL_IDS:
        raise ValueError("model_out_of_scope")
    if model_id != EXLAB_MODEL_ID:
        raise ValueError("model_not_allowlisted")
    return EXLAB_SPEC


# --------------------------------------------------------------------------
# Bounded parsing / safe classification helpers.
# --------------------------------------------------------------------------


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
    """Default transport. NOT reachable from a default invocation.

    It is only ever wired in when a caller explicitly asks for the real
    transport, which the workflow gate does only under an authorized
    single-use dispatch.
    """

    import urllib.error
    import urllib.request

    payload = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "padiem-b14-exlab-live-oneshot/1.0",
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


# Short synthetic Korean prompt with no customer data. The answer is never
# printed; only bounded evidence lines are emitted. max_tokens=32 matches the
# historical #4220/#4252 synthetic canary posture.
SYNTHETIC_KO_PROMPT = "합성 연결 점검입니다. '정상'이라는 두 글자로만 답하세요."
SYNTHETIC_MAX_TOKENS = 32


def canonical_chat_body(spec: ExLabSpec) -> dict[str, Any]:
    """Pin one exact manual route with explicit no-retry/no-fallback policy."""

    return {
        "model": spec.model_id,
        "messages": [
            {
                "role": "user",
                "content": SYNTHETIC_KO_PROMPT,
            }
        ],
        "temperature": 0,
        "max_tokens": SYNTHETIC_MAX_TOKENS,
        "stream": False,
        "business14": {
            "allow_external_fallback": False,
            "max_attempts": 1,
            "max_retries": 0,
        },
    }


# --------------------------------------------------------------------------
# Closed safe error-code vocabulary.
#
# Only these local, gate-owned codes may ever be projected to stdout. An
# upstream ``error.code`` is untrusted diagnostic input and is never echoed
# verbatim; anything outside this set becomes "unknown". "unparseable" is a
# local classification, not a provider value.
# --------------------------------------------------------------------------

SAFE_ENGINE_ERROR_CODES: frozenset[str] = frozenset(
    {
        "invalid_request_error",
        "authentication_error",
        "permission_error",
        "not_found_error",
        "rate_limit_error",
        "quota_exceeded",
        "overloaded_error",
        "api_error",
        "timeout_error",
        "upstream_error",
        "upstream_timeout",
        "upstream_server_error",
        "upstream_rate_limited_busy",
        "no_safe_route",
        "provider_error",
        "unavailable",
        "unparseable",
        "unknown",
    }
)


def _safe_error_code(payload: dict[str, Any]) -> str:
    """Project an untrusted provider error onto a closed local vocabulary."""

    error = payload.get("error")
    if not isinstance(error, dict):
        return "unknown"
    code = error.get("code")
    if not isinstance(code, str):
        return "unknown"
    return code if code in SAFE_ENGINE_ERROR_CODES else "unknown"


def _classify_latency(latency_ms: int) -> str:
    """Coarse, bounded latency bucket (no raw timing leak beyond evidence)."""

    if latency_ms < 0:
        return "unknown"
    if latency_ms < 2_000:
        return "fast"
    if latency_ms < 10_000:
        return "moderate"
    return "slow"


def _http_class(status: int) -> str:
    if status == 200:
        return "2xx"
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limited"
    if 500 <= status < 600:
        return "server_error"
    return "other"


def _emit(prefix: str, key: str, value: str) -> None:
    """Emit one bounded evidence line for the model."""

    print(f"{prefix}_{key}={value}")


def _emit_result(prefix: str, result: str) -> None:
    print(f"{prefix}_PRODUCTION_SMOKE={result}")


def _locks(provider_posts: int, retries: int) -> None:
    print(f"B14_CHAT_POST_COUNT={provider_posts}")
    print(f"NETWORK_RETRY_COUNT={retries}")
    print("RAW_RESPONSE_CONTENT_OUTPUT=0")
    print("PRIVATE_PAYLOAD_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print(f"MAX_PROVIDER_CALLS={MAX_PROVIDER_CALLS}")
    print(f"RETRY={RETRY}")
    print(f"FALLBACK={FALLBACK}")
    print("AUTO_ROUTE_USED=0")
    print("FALLBACK_CALL_COUNT=0")
    print("PRODUCTION_MUTATION=0")


# Safe answer-shape diagnostics: never print any upstream message value.
_SAFE_FINISH_REASONS = frozenset(
    {"stop", "length", "content_filter", "tool_calls", "function_call"}
)


def _emit_empty_answer_diagnostics(prefix: str, chat: dict[str, Any]) -> None:
    """Classify an HTTP-200-without-text response without emitting user data."""
    choices = chat.get("choices")
    first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = first.get("message")
    message = message if isinstance(message, dict) else {}
    content = message.get("content")
    state = (
        "null" if content is None else
        "empty_string" if content == "" else
        "whitespace_string" if isinstance(content, str) and not content.strip() else
        "non_string" if not isinstance(content, str) else
        "nonempty"
    )
    finish = first.get("finish_reason")
    finish = finish if isinstance(finish, str) and finish in _SAFE_FINISH_REASONS else "other_or_missing"
    usage = chat.get("usage")
    tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    safe_tokens = tokens if type(tokens) is int and 0 <= tokens <= 1_000_000 else "unknown"
    print(f"{prefix}_EMPTY_ANSWER_CONTENT_STATE=" + state)
    print(f"{prefix}_EMPTY_ANSWER_FINISH_REASON=" + finish)
    print(f"{prefix}_EMPTY_ANSWER_COMPLETION_TOKENS=" + str(safe_tokens))
    print(f"{prefix}_EMPTY_ANSWER_REQUESTED_MAX_TOKENS={SYNTHETIC_MAX_TOKENS}")
    print(f"{prefix}_EMPTY_ANSWER_PRIVATE_CONTENT_OUTPUT=0")


# --------------------------------------------------------------------------
# The bounded run.
# --------------------------------------------------------------------------


def run(
    model_id: str,
    transport: HttpTransport | None = None,
) -> int:
    """Run exactly one bounded live acceptance for the one exact ExLab model.

    ``transport`` is required. When it is ``None`` the call fails closed
    **before any request is constructed**, which is what makes a default
    invocation unable to reach Production. There is no retry loop and no
    fallback: any failure after at most one POST is recorded as a failure.
    """

    prefix = EXLAB_SPEC.evidence_prefix

    try:
        spec = resolve_exlab(model_id)
    except ValueError as exc:
        print(f"B14_EXLAB_LIVE_ONESHOT=FAIL_{exc}")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    if transport is None:
        _emit_result(prefix, "FAIL_TRANSPORT_NOT_AUTHORIZED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        print("B14_CHAT_POST_COUNT=0")
        print("NETWORK_RETRY_COUNT=0")
        return 1

    provider_posts = 0
    network_retries = 0

    health_status, health_raw = transport("GET", HEALTH_PATH, None)
    if health_status != 200:
        _emit_result(prefix, f"FAIL_HEALTH_HTTP_{health_status}")
        _emit(prefix, "HTTP_CLASS", _http_class(health_status))
        _locks(provider_posts, network_retries)
        return 1
    try:
        health = _bounded_json(health_raw)
    except ValueError as exc:
        _emit_result(prefix, f"FAIL_HEALTH_{exc}")
        _locks(provider_posts, network_retries)
        return 1

    business14 = health.get("business14")
    if not isinstance(business14, dict) or business14.get("provider_mode") != "live":
        _emit_result(prefix, "FAIL_PROVIDER_MODE")
        _locks(provider_posts, network_retries)
        return 1

    providers = business14.get("providers")
    if not isinstance(providers, list):
        _emit_result(prefix, "FAIL_PROVIDER_LIST")
        _locks(provider_posts, network_retries)
        return 1
    provider_entry = next(
        (
            item
            for item in providers
            if isinstance(item, dict) and item.get("id") == spec.provider_id
        ),
        None,
    )
    if not isinstance(provider_entry, dict) or provider_entry.get("registered") is not True:
        _emit_result(prefix, "FAIL_PROVIDER_NOT_REGISTERED")
        _locks(provider_posts, network_retries)
        return 1
    # Boolean credential-bound evidence only: the secret value is never read.
    # has_key=true never proves key identity or entitlement.
    has_key = provider_entry.get("has_key") is True
    _emit(prefix, "PROVIDER_REGISTERED", "YES")
    _emit(prefix, "CREDENTIAL_BOUND", "YES" if has_key else "NO")
    _emit(prefix, "EXPECTED_BINDING", spec.expected_binding)
    if not has_key:
        _emit_result(prefix, "FAIL_CREDENTIAL_NOT_READY")
        _locks(provider_posts, network_retries)
        return 1
    _emit(prefix, "CREDENTIAL_READY", "YES")

    models_status, models_raw = transport("GET", MODELS_PATH, None)
    if models_status != 200:
        _emit_result(prefix, f"FAIL_MODELS_HTTP_{models_status}")
        _emit(prefix, "HTTP_CLASS", _http_class(models_status))
        _locks(provider_posts, network_retries)
        return 1
    try:
        models = _bounded_json(models_raw)
    except ValueError as exc:
        _emit_result(prefix, f"FAIL_MODELS_{exc}")
        _locks(provider_posts, network_retries)
        return 1

    routes = models.get("registered_routes")
    if not isinstance(routes, list):
        _emit_result(prefix, "FAIL_ROUTE_LIST")
        _locks(provider_posts, network_retries)
        return 1
    route = next(
        (
            item
            for item in routes
            if isinstance(item, dict) and item.get("id") == spec.model_id
        ),
        None,
    )
    if not isinstance(route, dict):
        _emit_result(prefix, "FAIL_ROUTE_NOT_REGISTERED")
        _locks(provider_posts, network_retries)
        return 1
    if (
        route.get("provider_id") != spec.provider_id
        or route.get("upstream_model") != spec.upstream_model
    ):
        _emit_result(prefix, "FAIL_ROUTE_IDENTITY")
        _locks(provider_posts, network_retries)
        return 1
    # The served registry must also report the model enabled (catalog ==
    # enabled models). A disabled model fails closed before any provider POST.
    catalog = models.get("catalog")
    if not isinstance(catalog, list) or not any(
        isinstance(row, dict) and row.get("id") == spec.model_id for row in catalog
    ):
        _emit_result(prefix, "FAIL_ROUTE_NOT_ENABLED")
        _locks(provider_posts, network_retries)
        return 1
    _emit(prefix, "SOURCE_ON", "YES")
    _emit(prefix, "ROUTE_REGISTERED", "YES")
    _emit(prefix, "EXACT_MODEL_IDENTITY", "PASS")

    provider_posts += 1
    started = time.monotonic()
    chat_body = canonical_chat_body(spec)
    chat_status, chat_raw = transport("POST", CHAT_PATH, chat_body)
    latency_ms = max(0, int((time.monotonic() - started) * 1000))

    _emit(prefix, "HTTP_CLASS", _http_class(chat_status))
    if chat_status != 200:
        try:
            payload = _bounded_json(chat_raw)
            error_code = _safe_error_code(payload)
        except ValueError:
            error_code = "unparseable"
        _emit_result(prefix, f"FAIL_CHAT_HTTP_{chat_status}")
        print(f"{prefix}_ENGINE_ERROR_CODE={error_code}")
        # #4220/#4252 lesson: a 429 is recorded as busy/admission-vs-quota
        # UNKNOWN without vendor proof; 5xx/timeout as capacity-or-transport
        # UNKNOWN. Neither is ever attributed to a specific quota/key cause
        # or retried here.
        if chat_status == 429:
            print(f"{prefix}_429_CLASS=admission_or_quota_unknown")
        elif chat_status in (502, 503, 504):
            print(f"{prefix}_5XX_CLASS=capacity_or_transport_unknown")
        _locks(provider_posts, network_retries)
        return 1

    try:
        chat = _bounded_json(chat_raw)
    except ValueError as exc:
        _emit_result(prefix, f"FAIL_CHAT_{exc}")
        _locks(provider_posts, network_retries)
        return 1

    meta = chat.get("business14")
    if not isinstance(meta, dict):
        _emit_result(prefix, "FAIL_METADATA_MISSING")
        _locks(provider_posts, network_retries)
        return 1

    checks = {
        "mode": meta.get("mode") == "live",
        "provider_mode": meta.get("provider_mode") == "live",
        "provider": meta.get("provider") == spec.provider_name,
        "selected_provider": meta.get("selected_provider") == spec.provider_name,
        "model_route": meta.get("model_route") == spec.model_id,
        "selected_model": meta.get("selected_model") == spec.model_id,
        "upstream_model": meta.get("upstream_model") == spec.upstream_model,
        "selected_upstream_model": meta.get("selected_upstream_model") == spec.upstream_model,
        "actual_response_model": meta.get("actual_response_model") == spec.upstream_model,
        "route_mode": meta.get("route_mode") == "manual",
        "fallback_used": meta.get("fallback_used") is False,
        "attempt_count": meta.get("attempt_count") == 1,
        "route_evidence_status": meta.get("route_evidence_status") == "live_verified",
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        _emit_result(prefix, "FAIL_ROUTE_METADATA")
        print(f"{prefix}_FAILED_METADATA_CHECKS=" + ",".join(sorted(failed)))
        _locks(provider_posts, network_retries)
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
        _emit_result(prefix, "FAIL_EMPTY_ANSWER")
        _emit_empty_answer_diagnostics(prefix, chat)
        _locks(provider_posts, network_retries)
        return 1

    _emit_result(prefix, "PASS")
    _emit(prefix, "MODEL_ID", spec.model_id)
    _emit(prefix, "UPSTREAM_MODEL", spec.upstream_model)
    _emit(prefix, "PROVIDER_PROTOCOL", PROVIDER_PROTOCOL)
    _emit(prefix, "PROVIDER_CHAT_PATH", PROVIDER_CHAT_PATH)
    _emit(prefix, "ACTUAL_RESPONSE_MODEL_EVIDENCE", "PASS")
    _emit(prefix, "MODEL_ID_MATCH", "YES")
    _emit(prefix, "PROVIDER_MATCH", "YES")
    _emit(prefix, "FALLBACK_USED", "NO")
    _emit(prefix, "ATTEMPT_COUNT", "1")
    _emit(prefix, "LATENCY_MS", str(latency_ms))
    _emit(prefix, "LATENCY_CLASS", _classify_latency(latency_ms))
    _emit(prefix, "STREAMING", "NOT_TESTED")
    _locks(provider_posts, network_retries)
    return 0


# --------------------------------------------------------------------------
# Served-version guard.
#
# The canonical rule is NOT reimplemented here. The whole Cloudflare
# deployments envelope is handed to the shared canonical resolver
# (``cloudflare_served_version.resolve_served_version_id``).
# --------------------------------------------------------------------------


def resolve_active_served_version(payload: object) -> str:
    """Return the active served version id using the canonical resolver."""

    return resolve_served_version_id(payload)


def assert_served_version(payload: object, expected_version: str) -> str:
    """Return the served version id only when it equals ``expected_version``."""

    served = resolve_served_version_id(payload)
    if served != expected_version:
        raise ServedVersionResolutionError(ServedVersionReason.VERSION_ID)
    return served


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Requires the one exact ExLab model id and an explicit authorization
    marker. Without both, this exits non-zero and never constructs a
    transport, so a bare default invocation cannot reach Production.
    """

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("B14_EXLAB_LIVE_ONESHOT=FAIL_MODEL_REQUIRED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 1
    model_id = args[0]
    if "--authorized-live-run" not in args[1:]:
        print("B14_EXLAB_LIVE_ONESHOT=FAIL_AUTHORIZATION_REQUIRED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 1
    return run(
        model_id,
        transport=_request,
    )


if __name__ == "__main__":
    sys.exit(main())
