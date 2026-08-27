"""FastAPI router for the BYOK Gateway Pilot API (Phase 2).

Routes:
- GET  /api/pilot/health      — Pilot health check (multi-provider if configured)
- GET  /api/pilot/models      — List pilot-available models
- POST /api/pilot/v1/chat/completions — Chat completions via BYOK with routing

Supports multi-provider registry and legacy single-provider fallback.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from starlette.routing import Router
from starlette.responses import JSONResponse
from starlette.requests import Request

from app.pilot.config import pilot_settings
from app.pilot.errors import (
    InvalidRequest,
    MissingProviderKey,
    NoSafeRoute,
    PilotNotConfigured,
    PlaceholderKeyRejected,
    PilotError,
    StreamNotSupported,
    ToolsNotSupported,
)
from app.pilot.redaction import redact_sensitive
from app.pilot.registry import get_registry
from app.pilot.routing import (
    PilotConfigurationState,
    resolve_configuration,
    resolve_route,
)
from app.pilot.schemas import PilotChatRequest
from app.pilot.openrouter_config import openrouter_config
from app.pilot.catalog import get_catalog_by_id, list_catalog_summaries
from app.pilot import provider as prv
from app.pilot import openrouter as orv
from app.pilot import router_core as rcore
from app.pilot import platform as plat

logger = logging.getLogger("korean-ai-platform.pilot")

router = Router()

_INVALID_REGISTRY_MESSAGE = "Provider registry 설정이 올바르지 않습니다."


# Allowed fields for PilotChatRequest (dataclass field names)
_VALID_ROLES = frozenset({"system", "user", "assistant"})
_ALLOWED_CHAT_FIELDS = frozenset({
    "model", "messages", "temperature", "max_tokens", "stream", "tools",
    "business14",
})
_ALLOWED_MESSAGE_FIELDS = frozenset({"role", "content"})
_ALLOWED_B14_FIELDS = frozenset({
    "task_type", "required_capabilities", "optimize_for",
    "allow_external_fallback", "provider_order", "max_attempts",
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

    # model
    if not isinstance(raw.get("model"), str) or not raw["model"].strip():
        raise _InvalidBody("model must be a non-empty string")

    model = raw["model"].strip()
    if len(model) > 200:
        raise _InvalidBody("model must not exceed 200 characters")

    # messages
    msgs = raw.get("messages")
    if not isinstance(msgs, list):
        raise _InvalidBody("messages must be a non-empty array")
    if len(msgs) < 1 or len(msgs) > 100:
        raise _InvalidBody("messages must have 1–100 items")

    validated_messages: list[dict[str, str]] = []
    for i, msg in enumerate(msgs):
        if not isinstance(msg, dict):
            raise _InvalidBody(f"messages[{i}] must be a JSON object")
        m_extra = set(msg) - _ALLOWED_MESSAGE_FIELDS
        if m_extra:
            raise _InvalidBody(f"messages[{i}] unexpected fields: {', '.join(sorted(m_extra))}")
        role = msg.get("role")
        if role not in _VALID_ROLES:
            raise _InvalidBody(f"messages[{i}] role must be one of system/user/assistant")
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            raise _InvalidBody(f"messages[{i}] content must be a non-empty string")
        content = content.strip()
        if len(content) > 32000:
            raise _InvalidBody(f"messages[{i}] content must not exceed 32000 characters")
        validated_messages.append({"role": role, "content": content})

    # temperature
    temp = raw.get("temperature")
    if temp is not None:
        if isinstance(temp, bool) or not isinstance(temp, (int, float)):
            raise _InvalidBody("temperature must be a number or null")
        temp = float(temp)
        if temp < 0.0 or temp > 2.0:
            raise _InvalidBody("temperature must be between 0.0 and 2.0")

    # max_tokens
    mt = raw.get("max_tokens")
    if mt is not None:
        if isinstance(mt, bool) or not isinstance(mt, int):
            raise _InvalidBody("max_tokens must be an integer or null")
        if mt < 1 or mt > 4096:
            raise _InvalidBody("max_tokens must be between 1 and 4096")

    # stream
    st = raw.get("stream")
    if st is not None and not isinstance(st, bool):
        raise _InvalidBody("stream must be a boolean or null")
    if st:
        raise StreamNotSupported()

    # tools
    tl = raw.get("tools")
    if tl is not None:
        if not isinstance(tl, list):
            raise _InvalidBody("tools must be an array or null")
        raise ToolsNotSupported()

    return {
        "model": model,
        "messages": validated_messages,
        "temperature": float(temp) if temp is not None else 0.2,
        "max_tokens": int(mt) if mt is not None else 300,
        "business14": _validate_b14_options(raw.get("business14")),
    }


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
        if isinstance(ma, bool) or not isinstance(ma, int) or ma < 1 or ma > 5:
            raise _InvalidBody("business14.max_attempts must be an integer between 1 and 5")
        opts["max_attempts"] = ma

    return opts


def _is_alpha_model(model_id: str) -> bool:
    """Check if a model ID is a Business 14 catalog model or b14/auto."""
    if model_id.strip() == "b14/auto":
        return True
    return get_catalog_by_id(model_id) is not None


def _catalog_summary_dicts() -> list[dict]:
    """Return catalog models as display dicts with extra Alpha fields."""
    result = []
    for m in list_catalog_summaries():
        result.append({
            "id": m["model_id"],
            "name": m["name"],
            "provider_id": "openrouter",
            "provider_name": m["provider"],
            "pilot_available": True,
            "input_krw_per_1k": None,
            "output_krw_per_1k": None,
            "tags": ["alpha", "openrouter"] + list(m["capabilities"]),
            "input_price_usd_per_1m": m["input_price_usd_per_1m"],
            "output_price_usd_per_1m": m["output_price_usd_per_1m"],
            "korean_score": m["korean_score"],
            "context_window": m["context_window"],
        })
    result.insert(0, {
        "id": "b14/auto",
        "name": "Business 14 자동 선택",
        "provider_id": "openrouter",
        "provider_name": "OpenRouter",
        "pilot_available": True,
        "input_krw_per_1k": None,
        "output_krw_per_1k": None,
        "tags": ["alpha", "openrouter", "auto"],
        "input_price_usd_per_1m": 0,
        "output_price_usd_per_1m": 0,
        "korean_score": 0,
        "context_window": 0,
    })
    return result


@router.route("/health", methods=["GET"])
async def pilot_health(request: Request):
    """Pilot health check. Includes Alpha (OpenRouter) and BYOK status."""
    state = resolve_configuration()

    b14_info = {
        "provider_mode": openrouter_config.provider_mode,
        "has_key": openrouter_config.has_key,
        "base_url_host": openrouter_config.base_url,
        "site_name": openrouter_config.site_name,
        "catalog_models": len(list_catalog_summaries()),
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
        resp.headers["business14-provider-mode"] = openrouter_config.provider_mode
        return resp

    if state == PilotConfigurationState.LEGACY:
        return JSONResponse({
            "status": "ok",
            "mode": "byok-pilot",
            "configured_providers": 1,
            "configured_models": 1,
            "business14": b14_info,
        })

    if openrouter_config.is_live and openrouter_config.has_key:
        return JSONResponse({
            "status": "ok",
            "mode": "business14-openrouter-live",
            "configured_providers": 1,
            "configured_models": len(list_catalog_summaries()),
            "business14": b14_info,
        })

    return JSONResponse({
        "status": "not_configured",
        "mode": "not_configured",
        "configured_providers": 0,
        "configured_models": 0,
        "business14": b14_info,
    })


@router.route("/models", methods=["GET"])
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
        })

    return JSONResponse({
        "models": [],
        "configured": False,
        "catalog": _catalog_summary_dicts(),
    })


@router.route("/router/resolve", methods=["POST"])
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
        raw_body = await request.json()
        body = _validate_body(raw_body)

        model_id = body["model"]
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
            "max_attempts": decision.max_attempts,
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
                    "provider_mode": openrouter_config.provider_mode,
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
    except Exception:
        logger.error(
            "pilot_resolve_unexpected_error request_id=%s",
            request_id,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "요청을 처리하는 중 내부 오류가 발생했습니다. Request ID로 관리자에게 문의하십시오.",
                    "request_id": request_id,
                }
            },
        )


async def _handle_alpha_chat(request_id: str, body: dict) -> JSONResponse:
    """Handle a chat completions request in Alpha (OpenRouter catalog) mode.

    - Detects mock vs live mode from B14_PROVIDER_MODE
    - In mock mode: returns canned response, zero upstream calls
    - In live mode: calls OpenRouter with fallback logic
    - Response metadata describes the candidate that ACTUALLY answered
      (after any fallback), never the primary decision candidate
    - Unknown exceptions fail closed (no fallback)
    """
    from app.pilot.openrouter_config import openrouter_config as cfg

    model_id = body["model"]
    b14_opts = body.get("business14", {})

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
            "route_id": fc.get("route_id", f"openrouter:{fc['model_id']}"),
        }
        for fc in decision.eligible_fallback
    ] if decision.fallback_allowed else []

    max_attempts = decision.max_attempts

    start_time = time.monotonic()
    attempt_count = 0
    fallback_used = False
    last_error: PilotError | None = None
    response_data: dict[str, Any] | None = None
    success_candidate: dict[str, str] | None = None
    attempt_evidence: list[dict[str, Any]] = []

    candidates: list[dict[str, str]] = [
        {
            "model_id": candidate.model_id,
            "upstream_model": candidate.upstream_model,
            "provider": candidate.provider,
            "route_id": candidate.route_id,
        }
    ] + fallback_candidates

    for idx in range(min(max_attempts, len(candidates))):
        attempt_count = idx + 1
        current = candidates[idx]

        if attempt_count > 1:
            fallback_used = True
            logger.info(
                "alpha_fallback attempt=%d model=%s",
                attempt_count,
                current["model_id"],
            )

        try:
            if decision.credential_source == "platform_secret":
                response_data = await plat.call_platform_chat_completions(
                    model_id=current["model_id"],
                    upstream_model=current["upstream_model"],
                    provider=current["provider"],
                    platform_provider_id=decision.platform_provider_id,
                    messages=body["messages"],
                    temperature=body.get("temperature"),
                    max_tokens=body.get("max_tokens"),
                )
            elif cfg.is_mock:
                response_data = await orv.call_openrouter_chat_completions(
                    messages=body["messages"],
                    temperature=body.get("temperature"),
                    max_tokens=body.get("max_tokens"),
                    model_id=current["model_id"],
                    upstream_model=current["upstream_model"],
                    provider=current["provider"],
                )
            else:
                if not cfg.has_key:
                    raise PilotNotConfigured(
                        "LIVE 모드에서는 OPENROUTER_API_KEY가 필요합니다. "
                        ".env 파일에 키를 설정하거나 B14_PROVIDER_MODE=mock로 전환하십시오."
                    )
                response_data = await orv.call_openrouter_chat_completions(
                    messages=body["messages"],
                    temperature=body.get("temperature"),
                    max_tokens=body.get("max_tokens"),
                    model_id=current["model_id"],
                    upstream_model=current["upstream_model"],
                    provider=current["provider"],
                )
        except PilotError as e:
            last_error = e
            attempt_evidence.append({
                "attempt": attempt_count,
                "model_id": current["model_id"],
                "upstream_model": current["upstream_model"],
                "provider": current["provider"],
                "route_id": current["route_id"],
                "outcome": "error",
                "error_code": e.code,
                "actual_response_model": None,
            })
            if not rcore.is_error_fallback_allowed(e.code):
                break
            if attempt_count >= max_attempts or idx >= len(candidates) - 1:
                break
            continue
        except Exception as e:
            logger.error(
                "alpha_unexpected_error request_id=%s model=%s error=%s",
                request_id,
                current["model_id"],
                redact_sensitive(str(e)),
            )
            attempt_evidence.append({
                "attempt": attempt_count,
                "model_id": current["model_id"],
                "upstream_model": current["upstream_model"],
                "provider": current["provider"],
                "route_id": current["route_id"],
                "outcome": "error",
                "error_code": "internal_error",
                "actual_response_model": None,
            })
            last_error = PilotError(
                code="internal_error",
                message="요청을 처리하는 중 내부 오류가 발생했습니다. Request ID로 관리자에게 문의하십시오.",
                status_code=500,
            )
            break

        actual_model = response_data.get("_actual_response_model")
        attempt_evidence.append({
            "attempt": attempt_count,
            "model_id": current["model_id"],
            "upstream_model": current["upstream_model"],
            "provider": current["provider"],
            "route_id": current["route_id"],
            "outcome": "success",
            "error_code": None,
            "actual_response_model": actual_model,
        })
        success_candidate = current
        break

    latency_ms = int((time.monotonic() - start_time) * 1000)

    if response_data is None or success_candidate is None:
        if last_error is not None:
            logger.warning(
                "alpha_error request_id=%s code=%s status=%d attempt=%d",
                request_id,
                last_error.code,
                last_error.status_code,
                attempt_count,
            )
            return JSONResponse(
                status_code=last_error.status_code,
                content={
                    "error": {
                        "code": last_error.code,
                        "message": last_error.message,
                        "request_id": request_id,
                        "attempt_count": attempt_count,
                        "fallback_used": fallback_used,
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
        biz14 = orv.build_mock_metadata(
            request_id=request_id,
            model_id=success_candidate["model_id"],
            upstream_model=success_candidate["upstream_model"],
            provider=success_candidate["provider"],
        )
    else:
        usage = response_data.get("usage") or {}
        pt = usage.get("prompt_tokens")
        ct = usage.get("completion_tokens")
        tt = usage.get("total_tokens")
        biz14 = orv.build_live_metadata(
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


@router.route("/v1/chat/completions", methods=["POST"])
async def pilot_chat_completions(
    request: Request,
):
    """Execute a chat completion with routing.

    Supports two modes:
    - Alpha (Business 14 catalog): uses OpenRouter adapter with mock/live mode.
      Key read from OPENROUTER_API_KEY env var. Supports b14/auto.
    - BYOK (legacy): uses X-Business14-Provider-Key header. Uses registry/legacy routing.
    """
    request_id = f"b14req_{uuid.uuid4().hex[:12]}"
    logger.info(
        "pilot_request request_id=%s",
        request_id,
    )

    try:
        x_business14_provider_key = request.headers.get("x-business14-provider-key")
        raw_body = await request.json()

        body = _validate_body(raw_body)

        # Alpha mode: catalog model or b14/auto
        if _is_alpha_model(body["model"]):
            return await _handle_alpha_chat(request_id, body)

        # BYOK mode (legacy flow — unchanged)
        api_key = _validate_provider_key(x_business14_provider_key)

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
            "pilot_no_safe_route request_id=%s reason=%s",
            request_id,
            e.reason_code,
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
                    "provider_mode": openrouter_config.provider_mode,
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
        logger.error(
            "pilot_unexpected_error request_id=%s error=%s",
            request_id,
            redact_sensitive(str(e)),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "요청을 처리하는 중 내부 오류가 발생했습니다. Request ID로 관리자에게 문의하십시오.",
                    "request_id": request_id,
                }
            },
        )