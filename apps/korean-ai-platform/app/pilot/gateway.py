"""FastAPI router for the BYOK Gateway Pilot API (Phase 2).

Routes:
- GET  /api/pilot/health      — Pilot health check (multi-provider if configured)
- GET  /api/pilot/models      — List pilot-available models
- POST /api/pilot/v1/chat/completions — Chat completions via BYOK with routing

Supports multi-provider registry and legacy single-provider fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from typing import Any

import httpx
from starlette.routing import Route, Router
from starlette.responses import JSONResponse
from starlette.requests import Request

from app.pilot.config import pilot_settings
from app.pilot.errors import (
    InvalidRequest,
    MissingProviderKey,
    NoSafeRoute,
    PlaceholderKeyRejected,
    PilotError,
    StreamNotSupported,
    ToolsNotSupported,
    UpstreamTimeout,
)
from app.pilot.redaction import redact_sensitive
from app.pilot.call_ledger import (
    LedgerDraft,
    new_log_id,
    origin_from_headers,
    utc_now_iso,
)
from app.pilot.call_ledger_store import record_call
from app.pilot.deferred_writes import enqueue, skipped
from app.pilot.tool_channel import (
    model_supports_tools,
    require_tool_capability,
    validate_messages,
    validate_tool_choice,
    validate_tools,
)
from app.pilot.provider_timeout_diagnostics import log_gateway_deadline
from app.pilot.b14_timeout_policy import GATEWAY_WALL_SECONDS
from app.pilot.registry import get_registry
from app.pilot.routing import (
    PilotConfigurationState,
    resolve_configuration,
    resolve_route,
)
from app.pilot.schemas import PilotChatRequest
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.catalog import (
    CATALOG_BY_ID,
    CATALOG_MODELS,
    get_catalog_by_id,
    is_evidenced_free,
)
from app.pilot.platform_secrets import (
    any_platform_secret_present,
    list_platform_providers,
    live_ready,
    resolve_secret,
)
from app.pilot import provider as prv
from app.pilot import router_core as rcore
from app.pilot import platform as plat
from app.pilot.routing_policy import B14_AUTO_CHAIN, ROUTING_POLICY_ID
from app.pilot.owner_model_exclusions import excluded_from_owner_customer_selection
from app.pilot.model_registry_file import group_model_ids

# ---------------------------------------------------------------------------
# Bounded same-route retry for retryable upstream failures (#1982)
#
# Measured defect: the direct Kilo free route intermittently returns 504
# (Kilo Gateway's own ~10s limit on free models). Direct/manual routes used
# to attempt once and give up despite the failure being retryable.
#
# The provider-aligned retry budget limits *additional* retry/fallback
# dispatches, not the initial model inference. For both manual and auto routes the initial
# attempt is governed by model idle detection and caller cancellation.
# After it completes, additional physical requests are allowed only when
# the shared retry window has remaining budget. The old 60s Engine ceiling
# is an independent caller contract, not a B14 model-generation deadline.
# ---------------------------------------------------------------------------
_UPSTREAM_RETRY_MAX_RETRIES = 2
_UPSTREAM_RETRY_BACKOFF_SECONDS = (0.5, 1.0)
_UPSTREAM_RETRY_BUDGET_SECONDS = GATEWAY_WALL_SECONDS
# Retryable transport classes may be retried on a SAME route for explicit
# manual routes. The owner-designated auto chain gives each chain candidate at
# most one call, so a chain stays a two-call maximum for its two positions.
_SAME_ROUTE_RETRYABLE_CODES = frozenset({
    "upstream_timeout",
    "upstream_server_error",
    "upstream_rate_limited_busy",
})

logger = logging.getLogger("korean-ai-platform.pilot")


_INVALID_REGISTRY_MESSAGE = "Provider registry 설정이 올바르지 않습니다."
_INTERNAL_ERROR_MESSAGE = "요청을 처리하는 중 내부 오류가 발생했습니다. Request ID로 관리자에게 문의하십시오."


async def _read_json_body(request: Request) -> Any:
    """Read JSON through the ASGI body boundary, not Request.json().

    Cloudflare's Python Workers bridge can expose a request object whose
    convenience ``json()`` path differs from Starlette's CPython behavior.
    Reading bytes explicitly keeps the production and local paths aligned.
    """
    raw = await request.body()
    try:
        return json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _InvalidBody("Request body must be valid JSON") from exc


async def _platform_caller_denial(
    request: Request, request_id: str
) -> JSONResponse | None:
    """Refuse a platform-credential dispatch from an unproven caller.

    The catalog lane spends the platform's own Provider credentials, so it is
    reachable only by a proven server-to-server caller. Mock mode performs no
    Provider call and spends no platform credential, so the billing boundary
    does not exist there. BYOK never reaches this check: it uses the caller's
    own key and is handled by the separate legacy lane.
    """
    from .b14_runtime_config import runtime_config as cfg

    if cfg.is_mock:
        return None

    from .service_proof import service_proof_denial, service_proof_message

    denial = await service_proof_denial(request, await request.body())
    if denial is None:
        return None
    return JSONResponse(
        status_code=denial.status_code,
        content={
            "error": {
                "code": denial.code,
                "message": service_proof_message(),
                "request_id": request_id,
            }
        },
    )


def _log_unexpected_error(event: str, request_id: str, exc: Exception) -> None:
    message = redact_sensitive(str(exc))[:240]
    logger.error(
        "%s request_id=%s exception_type=%s exception_message=%s",
        event,
        request_id,
        type(exc).__name__,
        message,
    )


# Allowed fields for PilotChatRequest (dataclass field names)
_ALLOWED_CHAT_FIELDS = frozenset({
    "model", "messages", "temperature", "max_tokens", "stream", "tools",
    "tool_choice",
    "business14",
    "reasoning_effort", "top_p", "top_k", "min_p",
    "presence_penalty", "repetition_penalty",
    # #5824 PR-3a: the request-carried caller credential. Accepted only so this
    # validator can parse and classify it; it never reaches a response or the
    # ledger as anything but the label "user".
    "user_credential_ref", "user_credential",
})
_ALLOWED_B14_FIELDS = frozenset({
    "task_type", "required_capabilities", "optimize_for",
    "allow_external_fallback", "provider_order", "max_attempts",
    "max_retries", "allow_paid", "product_tier",
})
_B14_OPTIMIZE_FOR = frozenset({"balanced", "cost", "latency", "korean"})
_B14_TASK_TYPES = frozenset({"general", "korean", "coding", "document", "batch"})


class _InvalidBody(PilotError):
    """Request body validation error → HTTP 422."""

    def __init__(self, message: str) -> None:
        super().__init__(code="invalid_body", message=message, status_code=422)


def _new_request_id() -> str:
    return f"b14req_{uuid.uuid4().hex[:12]}"


def _registry_invalid_response() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "registry_invalid",
                "message": _INVALID_REGISTRY_MESSAGE,
                "request_id": _new_request_id(),
            }
        },
    )


# Placeholder patterns to reject
_PLACEHOLDER_PATTERNS = [
    "sk-your",
    "your-api-key",
    "test-key",
    "demo-key",
    "$kap_api_key",
    "placeholder",
]


def _is_placeholder_key(key: str) -> bool:
    lower = key.lower().strip()
    if not key or key == "":
        return False
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern in lower:
            return True
    if len(key) < 8:
        return True
    return False


def _validate_provider_key(x_business14_provider_key: str | None) -> str:
    if not x_business14_provider_key:
        raise MissingProviderKey()
    if _is_placeholder_key(x_business14_provider_key):
        raise PlaceholderKeyRejected()
    return x_business14_provider_key


def _validate_body(raw: Any) -> dict:
    """Deep-validate and normalize a chat completions JSON body → 422 on failure."""
    if not isinstance(raw, dict):
        raise _InvalidBody("Request body must be a JSON object")

    extra = set(raw) - _ALLOWED_CHAT_FIELDS
    if extra:
        raise _InvalidBody(f"Unexpected top-level fields: {', '.join(sorted(extra))}")

    from .user_credential import credential_from_body

    # Resolved before anything that could touch a credential plane: an unusable
    # credential is a shape/refusal problem, and it is answered with a code and
    # a fixed message that never repeat what was sent.
    credential = credential_from_body(raw)

    # model
    if not isinstance(raw.get("model"), str) or not raw["model"].strip():
        raise _InvalidBody("model must be a non-empty string")

    model = raw["model"].strip()
    if credential is not None and model == "b14/auto":
        # A caller-owned key names one provider and one model. The automatic
        # route would answer with a supplier the credential never offered, so
        # the combination is refused instead of silently served by one of them.
        raise _InvalidBody("b14/auto cannot be combined with a request credential")
    # Provider/model controls supported context size and message count.
    # B14 validates the message shape, not a second artificial context cap.
    msgs = raw.get("messages")
    if not isinstance(msgs, list):
        raise _InvalidBody("messages must be a non-empty array")
    if not msgs:
        raise _InvalidBody("messages must be a non-empty array")

    validated_messages = validate_messages(msgs)

    # temperature
    temp = raw.get("temperature")
    if temp is not None:
        if isinstance(temp, bool) or not isinstance(temp, (int, float)):
            raise _InvalidBody("temperature must be a number or null")
        temp = float(temp)
        if not math.isfinite(temp):
            raise _InvalidBody("temperature must be finite; provider validates its supported range")

    # max_tokens. None is meaningful: preserve omission so a product may either
    # request an explicit bounded budget or defer to the provider/model default.
    mt = raw.get("max_tokens")
    if mt is not None:
        if isinstance(mt, bool) or not isinstance(mt, int):
            raise _InvalidBody("max_tokens must be an integer or null")
        if mt < 1:
            raise _InvalidBody("max_tokens must be positive; provider validates its supported maximum")

    # stream
    st = raw.get("stream")
    if st is not None and not isinstance(st, bool):
        raise _InvalidBody("stream must be a boolean or null")
    if st:
        raise StreamNotSupported()

    # tools
    # #5536: the tool channel. The declaration is validated here, before any
    # provider call, so a malformed declaration never reaches a provider and
    # never spends a credential.
    declared_tools = validate_tools(raw.get("tools"))
    tool_choice = validate_tool_choice(raw.get("tool_choice"), declared_tools)
    if tool_choice is not None and not declared_tools:
        raise _InvalidBody("tool_choice requires a declared tool")

    # Model-native overrides are opt-in. Reject unsupported vendor fields
    # instead of silently dropping or guessing an original-model default.
    from .model_native_parameters import (
        OPTIONAL_FIELDS, UnsupportedModelParameter, validate_native_parameters,
    )
    try:
        native_options = validate_native_parameters(
            model, {key: raw[key] for key in OPTIONAL_FIELDS if key in raw}
        )
    except UnsupportedModelParameter as exc:
        raise _InvalidBody(str(exc)) from exc

    body = {
        "model": model,
        "messages": validated_messages,
        "temperature": float(temp) if temp is not None else None,
        "max_tokens": int(mt) if mt is not None else None,
        "model_parameters": native_options,
        "tools": declared_tools,
        "tool_choice": tool_choice,
        "business14": _validate_b14_options(raw.get("business14")),
    }
    # Absent, not None: a request that carried no credential keeps the exact
    # body shape it had before this field existed.
    if credential is not None:
        body["user_credential"] = credential
    return body


def _validate_b14_options(raw: Any) -> dict:
    """Validate the optional business14 routing options block."""
    if raw is None:
        return {}

    if not isinstance(raw, dict):
        raise _InvalidBody("business14 must be a JSON object")

    extra = set(raw) - _ALLOWED_B14_FIELDS
    if extra:
        raise _InvalidBody(f"Unexpected business14 fields: {', '.join(sorted(extra))}")

    opts: dict = {}

    tier = raw.get("product_tier")
    if tier is not None:
        if not isinstance(tier, str) or tier not in ("free", "plus", "pro", "max"):
            raise _InvalidBody("business14.product_tier must be a supported product tier")
        opts["product_tier"] = tier

    tt = raw.get("task_type")
    if tt is not None:
        if not isinstance(tt, str) or tt not in _B14_TASK_TYPES:
            raise _InvalidBody(f"business14.task_type must be one of {sorted(_B14_TASK_TYPES)}")
        opts["task_type"] = tt

    rc = raw.get("required_capabilities")
    if rc is not None:
        if not isinstance(rc, list) or not all(isinstance(c, str) for c in rc):
            raise _InvalidBody("business14.required_capabilities must be an array of strings")
        opts["required_capabilities"] = list(rc)

    of = raw.get("optimize_for")
    if of is not None:
        if not isinstance(of, str) or of not in _B14_OPTIMIZE_FOR:
            raise _InvalidBody(f"business14.optimize_for must be one of {sorted(_B14_OPTIMIZE_FOR)}")
        opts["optimize_for"] = of

    aef = raw.get("allow_external_fallback")
    if aef is not None:
        if not isinstance(aef, bool):
            raise _InvalidBody("business14.allow_external_fallback must be a boolean")
        opts["allow_external_fallback"] = aef

    po = raw.get("provider_order")
    if po is not None:
        if not isinstance(po, list) or not all(isinstance(p, str) for p in po):
            raise _InvalidBody("business14.provider_order must be an array of strings")
        opts["provider_order"] = list(po)

    ma = raw.get("max_attempts")
    if ma is not None:
        # #4317: the option is accepted for wire compatibility and no longer
        # bounds anything. The number of candidates one dispatch may try is
        # the number of candidates the declared product grade allows.
        if isinstance(ma, bool) or not isinstance(ma, int) or ma < 1:
            raise _InvalidBody("business14.max_attempts must be a positive integer")

    mr = raw.get("max_retries")
    if mr is not None:
        if (
            isinstance(mr, bool)
            or not isinstance(mr, int)
            or mr < 0
        ):
            raise _InvalidBody("business14.max_retries must be a non-negative integer")
        opts["max_retries"] = mr

    ap = raw.get("allow_paid")
    if ap is not None:
        if not isinstance(ap, bool):
            raise _InvalidBody("business14.allow_paid must be a boolean")
        opts["allow_paid"] = ap

    return opts


def _is_alpha_model(model_id: str) -> bool:
    """Check if a model ID is a Business 14 catalog model or b14/auto."""
    if model_id.strip() == "b14/auto":
        return True
    return get_catalog_by_id(model_id) is not None


def _providers_with_registered_routes() -> list:
    """Return registered platform providers that own at least one CATALOG_BY_ID route."""
    provider_ids = {
        model.platform_provider_id
        for model in CATALOG_BY_ID.values()
        if model.enabled and model.provider_type == "platform"
    }
    return [
        spec for spec in list_platform_providers()
        if spec.provider_id in provider_ids
    ]


def _registered_route_dicts() -> list[dict]:
    """Return the exact-ID route registry surface without prices or secrets.

    ``public`` marks the CATALOG_MODELS auto lane, ``explicit_only`` the
    manual-pin lane, ``auto_eligible`` the free public lane.
    """
    public_ids = {model.model_id for model in CATALOG_MODELS}
    entries = []
    for model in sorted(CATALOG_BY_ID.values(), key=lambda m: m.model_id):
        is_public = model.model_id in public_ids
        is_free = is_evidenced_free(model)
        owner_excluded = excluded_from_owner_customer_selection(model.model_id)
        entries.append({
            "id": model.model_id,
            "provider_id": model.platform_provider_id,
            "upstream_model": model.upstream_model,
            "capabilities": sorted(model.capabilities),
            "free": is_free,
            "public": is_public,
            "explicit_only": not is_public,
            # Preserve registry provenance but never present owner-excluded
            # models as auto-eligible for B66 or another product consumer.
            "owner_excluded": owner_excluded,
            "auto_eligible": is_public and is_free and not owner_excluded,
        })
    return entries


def _catalog_summary_dicts() -> list[dict]:
    """All approved exact models from B14 JSON, with no synthetic auto option."""
    return [
        {
            "id": m.model_id,
            "name": m.display_name,
            "provider_id": m.platform_provider_id,
            "provider_name": m.provider,
            "pilot_available": m.enabled,
            "input_krw_per_1k": None,
            "output_krw_per_1k": None,
            "tags": sorted(m.capabilities),
            "input_price_usd_per_1m": m.input_price_usd_per_1m,
            "output_price_usd_per_1m": m.output_price_usd_per_1m,
            "context_window": m.context_window,
        }
        for m in sorted(CATALOG_BY_ID.values(), key=lambda m: m.model_id) if m.enabled
    ]


async def pilot_health(request: Request):
    """Pilot health check. Includes Alpha (platform catalog) and BYOK status."""
    from .platform_secrets import ensure_all_platform_secrets
    await ensure_all_platform_secrets()
    state = resolve_configuration()
    # Health must count the same enabled exact-model catalog as GET /models.
    # CATALOG_MODELS is the retired public/auto lane and may be empty even
    # when manual pinned routes in CATALOG_BY_ID are live and selectable.
    enabled_model_count = len(_catalog_summary_dicts())

    b14_info = {
        "provider_mode": runtime_config.provider_mode,
        "has_key": any_platform_secret_present(),
        "catalog_models": enabled_model_count,
        "routing_policy": {
            "id": ROUTING_POLICY_ID,
            "chain": list(B14_AUTO_CHAIN),
        },
        "providers": [
            {
                "id": spec.provider_id,
                "registered": True,
                "has_key": bool(resolve_secret(spec)),
            }
            for spec in sorted(
                _providers_with_registered_routes(),
                key=lambda item: item.provider_id,
            )
        ],
    }

    if state == PilotConfigurationState.VALID_REGISTRY:
        registry = get_registry()
        return JSONResponse({
            "status": "ok",
            "mode": "byok-multi-provider-pilot",
            "configured_providers": registry.provider_count,
            "configured_models": registry.model_count,
            "providers": registry.provider_summary(),
            "business14": b14_info,
        })

    if state == PilotConfigurationState.INVALID_REGISTRY:
        resp = _registry_invalid_response()
        resp.headers["business14-provider-mode"] = runtime_config.provider_mode
        return resp

    if state == PilotConfigurationState.LEGACY:
        return JSONResponse({
            "status": "ok",
            "mode": "byok-pilot",
            "configured_providers": 1,
            "configured_models": 1,
            "business14": b14_info,
        })

    if live_ready():
        return JSONResponse({
            "status": "ok",
            "mode": "b14-live",
            "configured_providers": len(_providers_with_registered_routes()),
            "configured_models": enabled_model_count,
            "registered_routes": len(CATALOG_BY_ID),
            "business14": b14_info,
        })

    return JSONResponse({
        "status": "not_configured",
        "mode": "not_configured",
        "configured_providers": 0,
        "configured_models": 0,
        "business14": b14_info,
    })


async def pilot_models(request: Request):
    """List models available for pilot (multi-provider if configured)."""
    state = resolve_configuration()

    if state == PilotConfigurationState.VALID_REGISTRY:
        registry = get_registry()
        return JSONResponse({
            "models": registry.list_models(),
            "configured": True,
            "mode": "multi-provider",
            "catalog": _catalog_summary_dicts(),
            "registered_routes": _registered_route_dicts(),
            "model_groups": group_model_ids(),
        })

    if state == PilotConfigurationState.INVALID_REGISTRY:
        return _registry_invalid_response()

    if state == PilotConfigurationState.LEGACY:
        display_name = pilot_settings.pilot_model_id
        provider_name = pilot_settings.pilot_provider_id
        return JSONResponse({
            "models": [
                {
                    "id": pilot_settings.pilot_model_id,
                    "name": display_name,
                    "provider_id": pilot_settings.pilot_provider_id,
                    "provider_name": provider_name,
                    "pilot_available": True,
                    "input_krw_per_1k": None,
                    "output_krw_per_1k": None,
                    "tags": ["pilot", "byok"],
                }
            ],
            "configured": True,
            "mode": "single-provider",
            "catalog": _catalog_summary_dicts(),
            "registered_routes": _registered_route_dicts(),
            "model_groups": group_model_ids(),
        })

    return JSONResponse({
        "models": [],
        "configured": False,
        "catalog": _catalog_summary_dicts(),
        "registered_routes": _registered_route_dicts(),
            "model_groups": group_model_ids(),
    })


async def pilot_router_resolve(
    request: Request,
):
    """Resolve a route without making any upstream calls.

    Accepts the same body shape as chat completions. Returns routing
    decision metadata including selected model, provider, fallback
    candidates, and credential availability.
    """
    request_id = f"b14req_{uuid.uuid4().hex[:12]}"

    try:
        x_business14_provider_key = request.headers.get("x-business14-provider-key")
        raw_body = await _read_json_body(request)
        body = _validate_body(raw_body)

        model_id = body["model"]
        from .auto_availability import ensure_generic_auto_enabled
        ensure_generic_auto_enabled(model_id)
        b14_opts = body.get("business14", {})

        if not _is_alpha_model(model_id):
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "unsupported_model",
                        "message": f"모델 '{model_id}'은(는) Business 14 Alpha 카탈로그에 없습니다. b14/auto 또는 카탈로그 모델 ID를 사용하십시오.",
                        "request_id": request_id,
                    }
                },
            )

        from .platform_secrets import ensure_route_secrets
        await ensure_route_secrets(
            model_id,
            allow_external_fallback=b14_opts.get(
                "allow_external_fallback", model_id == "b14/auto"
            ),
        )
        decision = rcore.resolve_route(model_id, b14_opts)

        return JSONResponse({
            "request_id": request_id,
            "route_mode": decision.route_mode,
            "selected_provider": decision.selected_provider,
            "selected_model": decision.selected_model,
            "selected_upstream_model": decision.selected_upstream_model,
            "selected_route_id": decision.selected_route_id,
            "reason_codes": decision.reason_codes,
            "fallback_allowed": decision.fallback_allowed,
            "fallback_used": False,
            "attempt_count": 1,
            "eligible_fallback": decision.eligible_fallback,
            "excluded_candidates": decision.excluded_candidates,
            "credential_available": decision.credential_available,
            "credential_status": decision.credential_status,
            "evidence_status": decision.evidence_status,
            "provider_mode": decision.provider_mode,
            # #4317: the candidates this route may try, in order. The count is
            # the whole budget; there is no separate attempt ceiling.
            "attempt_candidates": 1 + len(decision.eligible_fallback),
        })

    except NoSafeRoute as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "no_safe_route",
                    "message": e.message,
                    "request_id": request_id,
                    "reason_code": e.reason_code,
                    "upstream_called": e.upstream_called,
                    "provider_mode": runtime_config.provider_mode,
                }
            },
        )
    except PilotError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={
                "error": {
                    "code": e.code,
                    "message": e.message,
                    "request_id": request_id,
                }
            },
        )
    except Exception as exc:
        _log_unexpected_error("pilot_resolve_unexpected_error", request_id, exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": _INTERNAL_ERROR_MESSAGE,
                    "request_id": request_id,
                }
            },
        )


def _build_b14_mock_metadata(
    request_id: str,
    model_id: str,
    upstream_model: str,
    provider: str,
    routing_policy: str | None = None,
) -> dict[str, Any]:
    """Build Business 14 metadata for a mock response."""
    return {
        "provider_mode": "mock",
        "mode": "mock",
        "provider": provider,
        "model_route": model_id,
        "upstream_model": upstream_model,
        "actual_response_model": upstream_model,
        "latency_ms": 0,
        "request_id": request_id,
        "estimated_usd": None,
        "estimated_krw": None,
        "cost_basis": "unknown",
        "route_mode": "manual",
        "attempt_count": 1,
        "fallback_used": False,
        "evidence_status": "mock_no_upstream_call",
        "routing_policy": routing_policy,
    }


def _build_b14_live_metadata(
    request_id: str,
    model_id: str,
    upstream_model: str,
    provider: str,
    latency_ms: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    attempt_count: int = 1,
    fallback_used: bool = False,
    actual_response_model: str | None = None,
    routing_policy: str | None = None,
) -> dict[str, Any]:
    """Build Business 14 metadata for a live response.

    All arguments must describe the candidate that ACTUALLY answered
    (after any fallback), never the primary candidate.
    """
    cm = get_catalog_by_id(model_id)
    estimated_usd = None
    estimated_krw = None
    cost_basis = "unknown"
    if cm and prompt_tokens is not None and completion_tokens is not None:
        estimated_usd = cm.estimate_cost_usd(prompt_tokens, completion_tokens)
        estimated_krw = cm.estimate_cost_krw(prompt_tokens, completion_tokens)
        if cm.price_is_known:
            cost_basis = "known_free" if estimated_usd == 0.0 else "configured_snapshot"

    return {
        "provider_mode": "live",
        "mode": "live",
        "provider": provider,
        "model_route": model_id,
        "upstream_model": upstream_model,
        "actual_response_model": actual_response_model,
        "latency_ms": latency_ms,
        "request_id": request_id,
        "estimated_usd": estimated_usd,
        "estimated_krw": estimated_krw,
        "cost_basis": cost_basis,
        "route_mode": "auto" if model_id == "b14/auto" else "manual",
        "attempt_count": attempt_count,
        "fallback_used": fallback_used,
        "evidence_status": "live_verified",
        "routing_policy": routing_policy,
    }


def _first_finish_reason(response_data: dict[str, Any]) -> str | None:
    """The stop reason the provider reported, or None when it reported none.

    A missing reason stays missing in the ledger. Substituting ``stop`` would
    turn an absent provider field into a claim about how the answer ended.
    """
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    reason = first.get("finish_reason") if isinstance(first, dict) else None
    return reason if isinstance(reason, str) and reason.strip() else None


def _protocol_for(
    platform_provider_id: str | None,
    upstream_model: str | None,
    *,
    tools_declared: bool = False,
) -> str:
    """Which wire family this physical call actually used.

    The ledger records a protocol per attempt because a fallback chain can walk
    two providers that speak different transports. Anything the gateway cannot
    name is stored as ``unknown`` rather than assumed to be chat completions.
    #4727 added a second Google family: a declared tool is served by the native
    ``streamGenerateContent`` adapter, not by the compatible endpoint, so the
    row has to say which of the two answered.
    """
    if platform_provider_id == "opencode-go" and upstream_model:
        from .opencode_go_wire import _WIRE

        return _WIRE.get(upstream_model, "unknown")
    if platform_provider_id == "google":
        if tools_declared:
            return "native"
        return "chat/completions"
    return "chat/completions" if platform_provider_id else "unknown"


def _write_ledger_record(request_id: str, record) -> None:
    """Append one finished row, deferred until the caller has its answer.

    Mock mode performs no provider call, so it produces no execution record.
    Only the bounded storage status is logged: never a payload, never a value.
    """
    from .platform import _provider_mode

    if _provider_mode() == "mock":
        return

    async def write() -> None:
        status = await record_call(record)
        logger.info(
            "b14_ledger request_id=%s log_id=%s outcome=%s attempts=%d status=%s",
            request_id, record.log_id, record.outcome, record.attempt_count, status,
        )

    enqueue(write, request_id=request_id)


async def _handle_alpha_chat(
    request_id: str, body: dict, origin_headers: Any = None
) -> JSONResponse:
    """Handle a chat completions request in Alpha (platform catalog) mode.

    - Detects mock vs live mode from B14_PROVIDER_MODE
    - In mock mode: returns canned response, zero upstream calls
    - In live mode: calls the platform provider with fallback logic
    - Response metadata describes the candidate that ACTUALLY answered
      (after any fallback), never the primary decision candidate
    - Unknown exceptions fail closed (no fallback)
    """
    from app.pilot.b14_runtime_config import runtime_config as cfg

    model_id = body["model"]
    b14_opts = body.get("business14", {})

    # #5536: tool calling is served only by a registered model that declares
    # the tool capability. A pinned model is checked before any credential is
    # resolved, so a request that declares a tool for a model that cannot
    # serve one is refused before execution.
    declared_tools = body.get("tools") or []
    if declared_tools and model_id != "b14/auto":
        require_tool_capability(model_id)

    from .platform_secrets import ensure_route_secrets
    await ensure_route_secrets(
        model_id,
        allow_external_fallback=b14_opts.get(
            "allow_external_fallback", model_id == "b14/auto"
        ),
        product_tier=b14_opts.get("product_tier", "free"),
    )
    decision = rcore.resolve_route(model_id, b14_opts)

    candidate = rcore.RouteCandidate(
        model_id=decision.selected_model,
        upstream_model=decision.selected_upstream_model,
        provider=decision.selected_provider,
        provider_type="external",
        reason="alpha_route_resolution",
        route_id=decision.selected_route_id,
    )

    fallback_candidates = [
        {
            "model_id": fc["model_id"],
            "upstream_model": fc["upstream_model"],
            "provider": fc["provider"],
            "route_id": fc["route_id"],
            "platform_provider_id": fc.get("platform_provider_id", ""),
        }
        for fc in decision.eligible_fallback
    ] if decision.fallback_allowed else []

    # #4317: the candidate list is the whole budget. Every candidate the
    # declared product grade allows is tried, in order, and nothing narrows
    # that list.
    # B14 does not duplicate provider requests by default. Optional retries
    # require explicit caller opt-in and never widen the configured maximum.
    same_route_retry_limit = b14_opts.get("max_retries", 0)

    start_time = time.monotonic()
    deadline = start_time + _UPSTREAM_RETRY_BUDGET_SECONDS
    attempt_count = 0
    fallback_used = False
    last_error: PilotError | None = None
    response_data: dict[str, Any] | None = None
    success_candidate: dict[str, str] | None = None
    attempt_evidence: list[dict[str, Any]] = []
    # #5318: the ledger accumulates each physical attempt while the walk is
    # still in progress. A fallback that answered is only provable if the
    # attempt that failed was written down when it failed. Mock mode performs
    # no provider call, so it produces no execution record at all.
    ledger = None
    try:
        ledger = LedgerDraft(
            log_id=new_log_id(), request_id=request_id,
            endpoint="/api/pilot/v1/chat/completions",
            protocol=_protocol_for(decision.platform_provider_id, candidate.upstream_model),
            streaming=False, requested_model_id=model_id, started_at=utc_now_iso(),
            origin=origin_from_headers(origin_headers),
        )
    except Exception as ledger_exc:
        skipped(request_id, ledger_exc)

    def _write_ledger(record) -> None:
        _write_ledger_record(request_id, record)

    candidates: list[dict[str, str]] = [
        {
            "model_id": candidate.model_id,
            "upstream_model": candidate.upstream_model,
            "provider": candidate.provider,
            "route_id": candidate.route_id,
            "platform_provider_id": decision.platform_provider_id,
        }
    ] + fallback_candidates

    # #5536: the automatic route resolves to a concrete candidate, so the
    # same capability check runs on that candidate before any provider call.
    if declared_tools:
        require_tool_capability(candidates[0]["model_id"])

    async def _invoke_upstream_raw(current: dict[str, str]) -> dict[str, Any]:
        if decision.credential_source == "platform_secret":
            return await plat.call_platform_chat_completions(
                model_id=current["model_id"],
                upstream_model=current["upstream_model"],
                provider=current["provider"],
                platform_provider_id=current.get("platform_provider_id") or decision.platform_provider_id,
                messages=body["messages"],
                temperature=body.get("temperature"),
                max_tokens=body.get("max_tokens"),
                **({"model_parameters": body["model_parameters"]}
                   if body.get("model_parameters") else {}),
                # #5536: the tool declaration travels to the provider with the
                # request. It is present only when the caller declared a tool.
                **({"tools": body["tools"]} if body.get("tools") else {}),
                **({"tool_choice": body["tool_choice"]}
                   if body.get("tool_choice") is not None else {}),
            )
        raise InvalidRequest(
            "non-platform route is not routable (OpenRouter retired, #1933 S2)"
        )

    async def _invoke_upstream(current: dict[str, str]) -> dict[str, Any]:
        # Bounded physical call evidence, not a model/provider identity log.
        from app.stack_telemetry import record_stage
        started = time.perf_counter()
        try:
            result = await _invoke_upstream_raw(current)
        except Exception as exc:
            code = "timeout" if isinstance(exc, TimeoutError) else "provider_error"
            # Use only fixed buckets. Never emit provider exception messages.
            try:
                safe = getattr(exc, "code", "")
                if safe in ("upstream_timeout", "gateway_timeout"):
                    code = "timeout"
                elif safe in ("upstream_rate_limited", "rate_limited"):
                    code = "rate_limit"
            except Exception:
                pass
            record_stage("provider.call", False, (time.perf_counter()-started)*1000, code)
            raise
        record_stage("provider.call", True, (time.perf_counter()-started)*1000)
        return result

    budget_exhausted = False
    for idx in range(len(candidates)):
        if budget_exhausted:
            break
        current = candidates[idx]

        if idx > 0:
            fallback_used = True
            logger.info(
                "alpha_fallback attempt=%d model=%s",
                idx + 1,
                current["model_id"],
            )

        retry_index = 0
        succeeded = False
        unexpected_internal = False
        advance_to_next_candidate = False
        if declared_tools and not model_supports_tools(current["model_id"]):
            # #5536: a candidate that cannot serve a tool call is skipped
            # without a provider call. The tool declaration is never sent to a
            # model that cannot honor it.
            attempt_evidence.append({
                "attempt": attempt_count + 1,
                "model_id": current["model_id"],
                "upstream_model": current["upstream_model"],
                "provider": current["provider"],
                "route_id": current["route_id"],
                "outcome": "error",
                "error_code": "tools_not_supported",
                "retry_index": 0,
                "actual_response_model": None,
            })
            if ledger is not None:
                try:
                    ledger.record_attempt(
                        provider=current["provider"], model_id=current["model_id"],
                        upstream_model=current["upstream_model"], route_id=current["route_id"],
                        outcome="error", error_code="tools_not_supported", dispatched=False,
                        protocol=_protocol_for(
                            current.get("platform_provider_id") or decision.platform_provider_id,
                            current["upstream_model"],
                        ),
                    )
                except Exception as ledger_exc:
                    ledger = None
                    skipped(request_id, ledger_exc)
            last_error = ToolsNotSupported(current["model_id"])
            if idx < len(candidates) - 1:
                advance_to_next_candidate = True
            break
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                budget_exhausted = True
                if last_error is None:
                    last_error = UpstreamTimeout()
                break

            attempt_count += 1
            # #5318: the physical attempt boundary is where B14 measures its
            # own duration. Measuring it here rather than inside the adapter
            # covers the asyncio timeout too, where the adapter's coroutine is
            # cancelled and never reports a duration.
            attempt_started = time.perf_counter()
            # The first physical model attempt (manual OR auto) has no
            # arbitrary 45s wall cap. Later attempts retain retry budget.
            attempt_timeout = None if attempt_count == 1 else remaining
            try:
                async with asyncio.timeout(attempt_timeout):
                    response_data = await _invoke_upstream(current)
            except TimeoutError as exc:
                # asyncio.timeout hard ceiling fired (adapter timeout did not).
                # Fixed allowlisted metadata only; never log content or credentials.
                log_gateway_deadline(
                    logger, current.get("platform_provider_id") or decision.platform_provider_id,
                )
                timeout_error = UpstreamTimeout()
                timeout_error.__cause__ = exc
                error: PilotError = timeout_error
            except PilotError as exc:
                from .opencode_go_wire import log_go_vendor_error
                log_go_vendor_error(
                    logger, exc, request_id=request_id,
                    request_path="/api/pilot/v1/chat/completions", attempt=attempt_count,
                    fallback=idx > 0,
                )
                error = exc
            except Exception as exc:
                logger.error(
                    "alpha_unexpected_error request_id=%s model=%s error=%s",
                    request_id,
                    current["model_id"],
                    redact_sensitive(str(exc)),
                )
                attempt_evidence.append({
                    "attempt": attempt_count,
                    "model_id": current["model_id"],
                    "upstream_model": current["upstream_model"],
                    "provider": current["provider"],
                    "route_id": current["route_id"],
                    "outcome": "error",
                    "error_code": "internal_error",
                    "retry_index": retry_index,
                    "actual_response_model": None,
                })
                # #5318: an internal fault is still a physical attempt the
                # candidate made. It is recorded, not silently dropped, so the
                # dashboard never shows a clean single-attempt request that
                # actually burned an unexpected failure first.
                if ledger is not None:
                    try:
                        ledger.record_attempt(
                            provider=current["provider"], model_id=current["model_id"],
                            upstream_model=current["upstream_model"],
                            route_id=current["route_id"], outcome="error",
                            error_code="internal_error", retry_index=retry_index,
                            elapsed_ms=int((time.perf_counter() - attempt_started) * 1000),
                            protocol=_protocol_for(
                                current.get("platform_provider_id")
                                or decision.platform_provider_id,
                                current["upstream_model"],
                            ),
                        )
                    except Exception as ledger_exc:
                        ledger = None
                        skipped(request_id, ledger_exc)
                last_error = PilotError(
                    code="internal_error",
                    message="요청을 처리하는 중 내부 오류가 발생했습니다. Request ID로 관리자에게 문의하십시오.",
                    status_code=500,
                )
                unexpected_internal = True
                error = None
            else:
                actual_model = response_data.get("_actual_response_model")
                attempt_evidence.append({
                    "attempt": attempt_count,
                    "model_id": current["model_id"],
                    "upstream_model": current["upstream_model"],
                    "provider": current["provider"],
                    "route_id": current["route_id"],
                    "outcome": "success",
                    "error_code": None,
                    "retry_index": retry_index,
                    "actual_response_model": actual_model,
                })
                if ledger is not None:
                    try:
                        ledger.record_attempt(
                            provider=current["provider"], model_id=current["model_id"],
                            upstream_model=current["upstream_model"], route_id=current["route_id"],
                            outcome="success", retry_index=retry_index,
                            elapsed_ms=int((time.perf_counter() - attempt_started) * 1000),
                            usage=response_data.get("usage"),
                            actual_response_model=actual_model,
                            finish_reason=_first_finish_reason(response_data),
                            provider_request_id=response_data.get("id")
                            if isinstance(response_data.get("id"), str) else None,
                            protocol=_protocol_for(
                                current.get("platform_provider_id") or decision.platform_provider_id,
                                current["upstream_model"],
                            ),
                        )
                    except Exception as ledger_exc:
                        ledger = None
                        skipped(request_id, ledger_exc)
                success_candidate = current
                succeeded = True
                error = None

            if unexpected_internal or succeeded:
                break
            assert error is not None

            last_error = error
            attempt_evidence.append({
                "attempt": attempt_count,
                "model_id": current["model_id"],
                "upstream_model": current["upstream_model"],
                "provider": current["provider"],
                "route_id": current["route_id"],
                "outcome": "error",
                "error_code": error.code,
                "retry_index": retry_index,
                "actual_response_model": None,
            })
            if ledger is not None:
                try:
                    ledger.record_attempt(
                        provider=current["provider"], model_id=current["model_id"],
                        upstream_model=current["upstream_model"], route_id=current["route_id"],
                        outcome="error", error_code=error.code, retry_index=retry_index,
                        elapsed_ms=int((time.perf_counter() - attempt_started) * 1000),
                        protocol=_protocol_for(
                            current.get("platform_provider_id") or decision.platform_provider_id,
                            current["upstream_model"],
                        ),
                    )
                except Exception as ledger_exc:
                    ledger = None
                    skipped(request_id, ledger_exc)

            # Same-route bounded retry for explicit manual routes (#1982).
            # The candidate list is the whole budget, so a same-route retry
            # stays inside its own explicit limit and auto candidates advance
            # without a same-route retry.
            # Non-retryable classes (auth, bad request) never reach a retry:
            # they are not in _SAME_ROUTE_RETRYABLE_CODES and the
            # fallback-prohibited check below breaks on the first attempt.
            if (
                decision.route_mode != "auto"
                and
                error.code in _SAME_ROUTE_RETRYABLE_CODES
                and retry_index < same_route_retry_limit
            ):
                backoff = _UPSTREAM_RETRY_BACKOFF_SECONDS[
                    min(retry_index, len(_UPSTREAM_RETRY_BACKOFF_SECONDS) - 1)
                ]
                if deadline - time.monotonic() > backoff:
                    retry_index += 1
                    decision.reason_codes.append(f"upstream_retry:{retry_index}")
                    logger.info(
                        "alpha_upstream_retry request_id=%s attempt=%d code=%s backoff_s=%.1f",
                        request_id,
                        retry_index,
                        error.code,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

            if not rcore.is_error_fallback_allowed(error.code, reason=getattr(error, "reason", None)):
                break
            if idx >= len(candidates) - 1:
                break
            advance_to_next_candidate = True
            break  # -> next fallback candidate

        if succeeded or unexpected_internal:
            # Success ends the chain walk; an unknown exception fails closed
            # with no fallback (never advance on either path).
            break
        if not advance_to_next_candidate:
            # Non-fallback-allowed errors and exhausted attempts stop the
            # walk: reaching the next candidate requires an explicit advance
            # decision above (D14 #2044: multi-candidate chains made the old
            # fall-through walk every remaining candidate).
            break

    latency_ms = int((time.monotonic() - start_time) * 1000)

    if response_data is None or success_candidate is None:
        if last_error is not None:
            if not getattr(last_error, "_go_vendor_logged", False):
                logger.warning(
                    "alpha_error request_id=%s code=%s status=%d attempt=%d",
                    request_id,
                    last_error.code,
                    last_error.status_code,
                    attempt_count,
                )
            if ledger is not None:
                try:
                    _write_ledger(ledger.finish(
                        outcome="error", http_status=last_error.status_code,
                        error_code=last_error.code, elapsed_ms=latency_ms,
                        # Nothing answered, so no response model is claimed. The
                        # attempted selection is still recorded: it is what B14 chose
                        # and dispatched, and the attempt rows keep each provider.
                        selected_model_id=candidates[0]["model_id"],
                        selected_provider=candidates[0]["provider"],
                        selected_upstream_model=candidates[0]["upstream_model"],
                        selected_route_id=candidates[0]["route_id"],
                        route_mode=decision.route_mode,
                        fallback_used=fallback_used,
                        fallback_depth=len(candidates) - 1 if fallback_used else 0,
                    ))
                except Exception as ledger_exc:
                    skipped(request_id, ledger_exc)
            return JSONResponse(
                status_code=last_error.status_code,
                content={
                    "error": {
                        "code": last_error.code,
                        "message": last_error.message,
                        "request_id": request_id,
                        "attempt_count": attempt_count,
                        "fallback_used": fallback_used,
                        "reason_codes": decision.reason_codes,
                        "attempt_evidence": attempt_evidence,
                    }
                },
            )
        raise NoSafeRoute(
            reason_code="no_safe_route",
            message="안전한 라우팅 경로를 찾을 수 없습니다.",
            upstream_called=False,
        )

    actual_response_model = response_data.get("_actual_response_model")
    if cfg.is_mock:
        biz14 = _build_b14_mock_metadata(
            request_id=request_id,
            model_id=success_candidate["model_id"],
            upstream_model=success_candidate["upstream_model"],
            provider=success_candidate["provider"],
            routing_policy=ROUTING_POLICY_ID if decision.route_mode == "auto" else None,
        )
    else:
        usage = response_data.get("usage") or {}
        pt = usage.get("prompt_tokens")
        ct = usage.get("completion_tokens")
        tt = usage.get("total_tokens")
        biz14 = _build_b14_live_metadata(
            request_id=request_id,
            model_id=success_candidate["model_id"],
            upstream_model=success_candidate["upstream_model"],
            provider=success_candidate["provider"],
            latency_ms=latency_ms,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            attempt_count=attempt_count,
            fallback_used=fallback_used,
            actual_response_model=actual_response_model,
            routing_policy=ROUTING_POLICY_ID if decision.route_mode == "auto" else None,
        )

    usage = response_data.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")

    biz14.update({
        "route_mode": decision.route_mode,
        "selected_provider": success_candidate["provider"],
        "selected_model": success_candidate["model_id"],
        "selected_upstream_model": success_candidate["upstream_model"],
        "actual_response_model": actual_response_model,
        "selected_route_id": success_candidate["route_id"],
        "reason_codes": decision.reason_codes,
        "fallback_allowed": decision.fallback_allowed,
        "fallback_used": fallback_used,
        "attempt_count": attempt_count,
        "attempt_evidence": attempt_evidence,
        "route_evidence_status": (
            "mock_no_upstream_call" if cfg.is_mock else "live_verified"
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    })

    if actual_response_model:
        response_data["model"] = actual_response_model
    response_data["business14"] = biz14
    for internal_key in [k for k in response_data if k.startswith("_")]:
        del response_data[internal_key]

    # #5318: record construction is fail-open; storage is deferred until the
    # Worker has constructed the answer. Keep the actual answering candidate.
    if ledger is not None:
        try:
            ledger.protocol = _protocol_for(
                success_candidate.get("platform_provider_id") or decision.platform_provider_id,
                success_candidate["upstream_model"],
            )
            _write_ledger(ledger.finish(
                outcome="success", http_status=200,
                finish_reason=_first_finish_reason(response_data), elapsed_ms=latency_ms,
                usage=response_data.get("usage"),
                selected_model_id=success_candidate["model_id"],
                selected_provider=success_candidate["provider"],
                selected_upstream_model=success_candidate["upstream_model"],
                selected_route_id=success_candidate["route_id"],
                actual_response_model=actual_response_model,
                route_mode=decision.route_mode, fallback_used=fallback_used,
                fallback_depth=len(candidates) - 1 if fallback_used else 0,
            ))
        except Exception as ledger_exc:
            skipped(request_id, ledger_exc)

    logger.info(
        "alpha_success request_id=%s model=%s provider=%s mode=%s attempt=%d latency_ms=%d",
        request_id,
        success_candidate["model_id"],
        success_candidate["provider"],
        cfg.provider_mode,
        attempt_count,
        latency_ms,
    )

    return JSONResponse(response_data)


async def _handle_user_credential_chat(
    request: Request, request_id: str, body: dict, origin_headers: Any = None
) -> JSONResponse:
    """Serve one request with the key that arrived inside its own body (#5824).

    This lane resolves no platform credential and builds no roster: no
    ``ensure_route_secrets`` read, no tier candidate, no same-route retry. One
    provider, the caller's own key, one physical attempt, and the provider's own
    error code when it fails. Nothing here is tried again on another supplier,
    because a substitution would either spend a key the caller did not offer or
    answer with a model the caller did not choose.
    """
    from app.pilot.b14_runtime_config import runtime_config as cfg
    from .platform import call_user_credential_chat_completions
    from .user_credential import UserCredential

    credential: UserCredential = body["user_credential"]
    model_id = body["model"]
    route_id = "user_credential"

    # #5536's rule applies unchanged to a caller-owned key: B14 holds no
    # capability record for a model it did not register, so a tool declaration
    # is refused rather than forwarded unverified.
    if body.get("tools"):
        raise ToolsNotSupported(model_id)

    ledger: LedgerDraft | None = None
    try:
        ledger = LedgerDraft(
            log_id=new_log_id(), request_id=request_id,
            endpoint=request.url.path, protocol="chat/completions",
            streaming=False, requested_model_id=model_id, started_at=utc_now_iso(),
            origin=origin_from_headers(origin_headers),
        )
    except Exception as ledger_exc:
        skipped(request_id, ledger_exc)

    def _finish(record_kwargs: dict) -> None:
        if ledger is None:
            return
        try:
            _write_ledger_record(
                request_id,
                ledger.finish(
                    credential_source="user", fallback_used=False, fallback_depth=0,
                    route_mode="manual", selected_model_id=model_id,
                    selected_provider=credential.provider_id,
                    selected_upstream_model=credential.upstream_model,
                    selected_route_id=route_id,
                    **record_kwargs,
                ),
            )
        except Exception as ledger_exc:
            skipped(request_id, ledger_exc)

    transport = getattr(request.app.state, "stream_transport", None)
    if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
        raise InvalidRequest("Invalid streaming transport configuration.")

    start_time = time.monotonic()
    attempt_started = time.perf_counter()
    evidence = {
        "attempt": 1,
        "model_id": model_id,
        "upstream_model": credential.upstream_model,
        "provider": credential.provider_id,
        "route_id": route_id,
        "outcome": "error",
        "error_code": None,
        "retry_index": 0,
        "actual_response_model": None,
    }
    def _attempt_elapsed_ms() -> int:
        return int((time.perf_counter() - attempt_started) * 1000)

    try:
        response_data = await call_user_credential_chat_completions(
            credential=credential,
            messages=body["messages"],
            temperature=body.get("temperature"),
            max_tokens=body.get("max_tokens"),
            **({"transport": transport} if transport is not None else {}),
        )
    except PilotError as exc:
        evidence["error_code"] = exc.code
        if ledger is not None:
            try:
                ledger.record_attempt(
                    provider=credential.provider_id, model_id=model_id,
                    upstream_model=credential.upstream_model, route_id=route_id,
                    outcome="error", error_code=exc.code,
                    elapsed_ms=_attempt_elapsed_ms(),
                )
            except Exception as ledger_exc:
                skipped(request_id, ledger_exc)
        _finish({
            "outcome": "error", "http_status": exc.status_code, "error_code": exc.code,
            "elapsed_ms": int((time.monotonic() - start_time) * 1000),
        })
        logger.warning(
            "user_credential_error request_id=%s provider=%s code=%s status=%d",
            request_id, credential.provider_id, exc.code, exc.status_code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request_id,
                    "attempt_count": 1,
                    "fallback_used": False,
                    "reason_codes": [route_id],
                    "attempt_evidence": [evidence],
                }
            },
        )
    except Exception as exc:
        # The provider call raised something B14 does not model. The redacted
        # text is the only thing that leaves this branch, and a caller key is
        # never part of it: the value lives in one header built per call.
        logger.error(
            "user_credential_unexpected_error request_id=%s provider=%s error=%s",
            request_id,
            credential.provider_id,
            redact_sensitive(str(exc)),
        )
        evidence["error_code"] = "internal_error"
        if ledger is not None:
            try:
                ledger.record_attempt(
                    provider=credential.provider_id, model_id=model_id,
                    upstream_model=credential.upstream_model, route_id=route_id,
                    outcome="error", error_code="internal_error",
                    elapsed_ms=_attempt_elapsed_ms(),
                )
            except Exception as ledger_exc:
                skipped(request_id, ledger_exc)
        internal = PilotError(
            code="internal_error", message=_INTERNAL_ERROR_MESSAGE, status_code=500,
        )
        _finish({
            "outcome": "error", "http_status": 500, "error_code": "internal_error",
            "elapsed_ms": int((time.monotonic() - start_time) * 1000),
        })
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": internal.code,
                    "message": internal.message,
                    "request_id": request_id,
                    "attempt_count": 1,
                    "fallback_used": False,
                    "reason_codes": [route_id],
                    "attempt_evidence": [evidence],
                }
            },
        )

    latency_ms = int((time.monotonic() - start_time) * 1000)
    actual_response_model = response_data.get("_actual_response_model")
    usage = response_data.get("usage") or {}
    evidence["outcome"] = "success"
    evidence["actual_response_model"] = actual_response_model

    if ledger is not None:
        try:
            ledger.record_attempt(
                provider=credential.provider_id, model_id=model_id,
                upstream_model=credential.upstream_model, route_id=route_id,
                outcome="success", elapsed_ms=_attempt_elapsed_ms(),
                usage=response_data.get("usage"),
                actual_response_model=actual_response_model,
                finish_reason=_first_finish_reason(response_data),
                provider_request_id=response_data.get("id")
                if isinstance(response_data.get("id"), str) else None,
            )
        except Exception as ledger_exc:
            skipped(request_id, ledger_exc)

    if cfg.is_mock:
        biz14 = _build_b14_mock_metadata(
            request_id=request_id, model_id=model_id,
            upstream_model=credential.upstream_model, provider=credential.provider_id,
            routing_policy=None,
        )
    else:
        biz14 = _build_b14_live_metadata(
            request_id=request_id, model_id=model_id,
            upstream_model=credential.upstream_model, provider=credential.provider_id,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            attempt_count=1, fallback_used=False,
            actual_response_model=actual_response_model, routing_policy=None,
        )

    biz14.update({
        "route_mode": "manual",
        "selected_provider": credential.provider_id,
        "selected_model": model_id,
        "selected_upstream_model": credential.upstream_model,
        "selected_route_id": route_id,
        "actual_response_model": actual_response_model,
        "reason_codes": [route_id],
        "fallback_allowed": False,
        "fallback_used": False,
        "attempt_count": 1,
        "attempt_evidence": [evidence],
        "route_evidence_status": (
            "mock_no_upstream_call" if cfg.is_mock else "live_verified"
        ),
        # The caller can confirm from its own response that its key, not the
        # platform's, answered. The label is the only credential fact recorded.
        "credential_source": "user",
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    })

    if actual_response_model:
        response_data["model"] = actual_response_model
    response_data["business14"] = biz14
    for internal_key in [k for k in response_data if k.startswith("_")]:
        del response_data[internal_key]

    _finish({
        "outcome": "success", "http_status": 200,
        "finish_reason": _first_finish_reason(response_data), "elapsed_ms": latency_ms,
        "usage": response_data.get("usage"),
        "actual_response_model": actual_response_model,
    })

    logger.info(
        "user_credential_success request_id=%s model=%s provider=%s mode=%s latency_ms=%d",
        request_id, model_id, credential.provider_id, cfg.provider_mode, latency_ms,
    )
    return JSONResponse(response_data)


async def pilot_chat_completions(
    request: Request,
):
    """Execute a chat completion with routing.

    Supports two modes:
    - Alpha (Business 14 catalog): uses the platform provider adapter with
      mock/live mode (keyless Kilo Gateway free route; OpenRouter retired).
      Supports b14/auto.
    - BYOK (legacy): uses X-Business14-Provider-Key header. Uses registry/legacy routing.
    """
    request_id = f"b14req_{uuid.uuid4().hex[:12]}"
    logger.info(
        "pilot_request request_id=%s",
        request_id,
    )

    try:
        x_business14_provider_key = request.headers.get("x-business14-provider-key")
        raw_body = await _read_json_body(request)

        # #5824 PR-3a: a body-carried caller credential selects its own lane,
        # whatever the model id looks like. Neither the catalog roster nor the
        # legacy header path is consulted, and no platform credential is
        # resolved for the request. Caller identity is still required: the proof
        # answers who may make B14 dispatch a provider request, which is a
        # different question from whose key that request spends.
        from .user_credential import has_credential

        if has_credential(raw_body):
            if raw_body.get("stream") is True:
                from .stream_gateway import pilot_stream_preview

                return await pilot_stream_preview(request, parsed_body=raw_body)
            denial = await _platform_caller_denial(request, request_id)
            if denial is not None:
                return denial
            body = _validate_body(raw_body)
            return await _handle_user_credential_chat(
                request, request_id, body, origin_headers=request.headers
            )

        # Explicit stream=true on a registered, manual B14 model reuses the
        # independently validated SSE preview path. The original raw request
        # body stays cached on Request; preview performs the canonical
        # schema/route/secret checks, including no-fallback single-attempt.
        # No automatic stream=false upgrade or BYOK/b14-auto promotion.
        # This is a streaming wire opt-in, never an in-memory JSON cap bypass.
        if (
            isinstance(raw_body, dict)
            and raw_body.get("stream") is True
            and isinstance(raw_body.get("model"), str)
            and raw_body["model"] != "b14/auto"
            and _is_alpha_model(raw_body["model"])
        ):
            from .stream_gateway import pilot_stream_preview

            return await pilot_stream_preview(request, parsed_body=raw_body)

        body = _validate_body(raw_body)
        from .auto_availability import ensure_generic_auto_enabled
        ensure_generic_auto_enabled(body["model"])

        # Alpha mode: catalog model or future b14/auto
        if _is_alpha_model(body["model"]):
            # Platform-owned credentials are spent on this lane. Refuse an
            # unproven caller before any credential is resolved or any
            # Provider request is built.
            denial = await _platform_caller_denial(request, request_id)
            if denial is not None:
                return denial
            return await _handle_alpha_chat(request_id, body, origin_headers=request.headers)

        # BYOK mode (legacy flow — unchanged)
        api_key = _validate_provider_key(x_business14_provider_key)

        # #5536: the BYOK lane serves a caller's own provider and model, and
        # B14 holds no capability record for it. A tool declaration is
        # therefore refused here rather than forwarded unverified.
        if body.get("tools"):
            raise ToolsNotSupported(body["model"])

        route = resolve_route(body["model"])

        state = resolve_configuration()
        mode = "byok-multi-provider-pilot" if state == PilotConfigurationState.VALID_REGISTRY else "byok-pilot"

        logger.info(
            "pilot_route request_id=%s model=%s provider=%s state=%s",
            request_id,
            body["model"],
            route.provider_id,
            state.value,
        )

        start_time = time.monotonic()
        response_data = await prv.call_chat_completions(
            api_key=api_key,
            messages=body["messages"],
            temperature=body.get("temperature"),
            max_tokens=body.get("max_tokens"),
            base_url=route.base_url,
            upstream_model=route.upstream_model,
            timeout_seconds=route.timeout_seconds,
            response_model=route.model_id,
        )
        latency_ms = int((time.monotonic() - start_time) * 1000)

        response_data.setdefault("business14", {})
        response_data["business14"]["mode"] = mode
        response_data["business14"]["provider"] = route.provider_id
        response_data["business14"]["model_route"] = body["model"]
        response_data["business14"]["latency_ms"] = latency_ms
        response_data["business14"]["request_id"] = request_id
        response_data["business14"]["estimated_krw"] = None

        logger.info(
            "pilot_success request_id=%s mode=%s latency_ms=%d",
            request_id,
            mode,
            latency_ms,
        )

        return JSONResponse(response_data)

    except NoSafeRoute as e:
        logger.warning(
            "pilot_no_safe_route request_id=%s reason=%s credential_reason=%s",
            request_id,
            e.reason_code,
            getattr(e, "credential_reason", ""),
        )
        return JSONResponse(
            status_code=e.status_code,
            content={
                "error": {
                    "code": e.code,
                    "message": e.message,
                    "request_id": request_id,
                    "reason_code": e.reason_code,
                    "upstream_called": e.upstream_called,
                    "provider_mode": runtime_config.provider_mode,
                }
            },
        )
    except PilotError as e:
        logger.warning(
            "pilot_error request_id=%s code=%s status=%d",
            request_id,
            e.code,
            e.status_code,
        )
        return JSONResponse(
            status_code=e.status_code,
            content={
                "error": {
                    "code": e.code,
                    "message": e.message,
                    "request_id": request_id,
                }
            },
        )
    except Exception as e:
        _log_unexpected_error("pilot_unexpected_error", request_id, e)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": _INTERNAL_ERROR_MESSAGE,
                    "request_id": request_id,
                }
            },
        )


router = Router(
    routes=[
        Route("/health", pilot_health, methods=["GET"]),
        Route("/models", pilot_models, methods=["GET"]),
        Route("/router/resolve", pilot_router_resolve, methods=["POST"]),
        Route("/v1/chat/completions", pilot_chat_completions, methods=["POST"]),
    ]
)
