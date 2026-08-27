"""Router Core for Business 14 Alpha.

Implements Manual and Automatic (b14/auto) routing with deterministic
model selection, fallback logic, and no-safe-route handling.

Manual:
  - Specific catalog model ID → single upstream call
  - No provider switching unless explicit

Automatic:
  - model = "b14/auto"
  - Selects best model from catalog based on optimize_for, task_type,
    required_capabilities, allow_external_fallback, provider_order, max_attempts
  - Hard constraints applied before preferences
  - Deterministic result
  - Fallback on: timeout, transport failure, HTTP 429, HTTP 5xx
  - No fallback on: HTTP 400/401/403/404/409/422/any other 4xx,
    malformed request, malformed upstream response, missing key,
    unsupported feature, oversize response, unknown exceptions

Option enforcement (every accepted option changes the result):
  - allow_external_fallback=False → no fallback candidates, one attempt
  - provider_order → deterministic provider priority in candidate sorting
  - task_type → hard capability filter (+ korean scoring boost)

Resolve endpoint does NOT make upstream calls.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.pilot.catalog import (
    CatalogModel,
    get_catalog_by_id,
    get_catalog_models,
    filter_catalog as _filter_catalog,
    select_by_optimize,
)
from app.pilot.openrouter_config import openrouter_config
from app.pilot.errors import NoSafeRoute


class RouteMode(str, enum.Enum):
    MANUAL = "manual"
    AUTO = "auto"
    AUTO_FALLBACK = "auto_fallback"


class EvidenceStatus(str, enum.Enum):
    MOCK_NO_UPSTREAM_CALL = "mock_no_upstream_call"
    LIVE_VERIFIED = "live_verified"
    RESOLVED_NOT_CALLED = "resolved_not_called"
    LIVE_FAILED = "live_failed"


class NoKeyReason(str, enum.Enum):
    LIVE_MODE_REQUIRES_KEY = "live_mode_requires_key"
    NO_KEY_SET = "no_key_set"
    KEY_AVAILABLE = "key_available"


@dataclass(frozen=True)
class RouteCandidate:
    """A single routing candidate from the catalog."""
    model_id: str
    upstream_model: str
    provider: str
    provider_type: str
    reason: str
    route_id: str


@dataclass(frozen=True)
class AttemptEvidence:
    """Explicit per-attempt record kept for every upstream attempt.

    The successful attempt's evidence is the source of truth for response
    metadata (selected model/provider/upstream, actual response model and
    cost estimate) — never the primary decision's candidate.
    """
    attempt: int
    model_id: str
    upstream_model: str
    provider: str
    outcome: str  # "success" | "error"
    error_code: str | None = None
    actual_response_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "model_id": self.model_id,
            "upstream_model": self.upstream_model,
            "provider": self.provider,
            "outcome": self.outcome,
            "error_code": self.error_code,
            "actual_response_model": self.actual_response_model,
        }


@dataclass(frozen=True)
class RouteDecision:
    """Result of router core resolution (NO upstream call made)."""
    route_mode: str  # "manual" | "auto"
    selected_provider: str
    selected_model: str  # catalog model_id
    selected_upstream_model: str
    selected_route_id: str
    reason_codes: list[str]
    fallback_allowed: bool
    eligible_fallback: list[dict[str, str]]  # remaining candidates
    excluded_candidates: list[dict[str, str]]  # filtered-out candidates
    credential_available: bool
    credential_status: str  # key_available | no_key_set | live_mode_requires_key
    evidence_status: str
    request_id: str
    provider_mode: str
    max_attempts: int
    credential_source: str = ""  # platform_secret | openrouter | request_byok | none
    platform_provider_id: str = ""


def _new_request_id() -> str:
    return f"b14req_{uuid.uuid4().hex[:12]}"


def _check_credentials() -> tuple[bool, str]:
    """Check whether credentials are available for live mode."""
    if openrouter_config.is_live:
        if openrouter_config.has_key:
            return True, NoKeyReason.KEY_AVAILABLE.value
        return False, NoKeyReason.LIVE_MODE_REQUIRES_KEY.value
    # mock mode
    return False, NoKeyReason.NO_KEY_SET.value


def _credential_status_for(cm) -> tuple[bool, str, str, str]:
    """Resolve credential availability/status for a catalog model.

    Returns ``(available, status, source, platform_provider_id)``.
    ``platform_secret`` models read their own Provider binding; missing secret
    fails closed. Everything else defers to the OpenRouter adapter config.
    """
    if cm.credential_source == "platform_secret":
        from app.pilot import platform_secrets as ps

        spec = ps.get_platform_provider(cm.platform_provider_id)
        present = ps.is_secret_present(spec) if spec else False
        return (
            present,
            "key_available" if present else "no_key_set",
            "platform_secret",
            cm.platform_provider_id or "",
        )
    ok, status = _check_credentials()
    return ok, status, "openrouter", ""


def _platform_secret_present(cm) -> bool:
    """True if a platform_secret model's secret is present; non-secret models always True."""
    from app.pilot import platform_secrets as ps

    if cm.credential_source != "platform_secret":
        return True
    spec = ps.get_platform_provider(cm.platform_provider_id)
    return ps.is_secret_present(spec) if spec else False


def resolve_manual_route(
    model_id: str,
    allow_external_fallback: bool = False,
) -> RouteDecision:
    """Resolve a manual route for a specific model ID.

    Returns a RouteDecision. Does NOT make upstream calls.
    Raises NoSafeRoute if the model is not in the catalog or is disabled.

    Manual routes default to ``allow_external_fallback=False``: no fallback
    candidates, ``fallback_allowed=False``, ``max_attempts=1``.  Only when the
    caller explicitly passes ``allow_external_fallback=True`` are fallback
    candidates populated (subject to error-allow-list in the gateway).
    """
    request_id = _new_request_id()
    cm = get_catalog_by_id(model_id)

    if cm is None:
        raise NoSafeRoute(
            reason_code="model_not_in_catalog",
            message=f"모델 '{model_id}'은(는) 카탈로그에 없습니다.",
            upstream_called=False,
        )

    if not cm.enabled:
        raise NoSafeRoute(
            reason_code="model_disabled",
            message=f"모델 '{model_id}'은(는) 현재 비활성화되어 있습니다.",
            upstream_called=False,
        )

    cred_ok, cred_status, cred_source, plat_pid = _credential_status_for(cm)

    # Platform-owned secret missing -> fail closed with zero upstream calls.
    if cred_source == "platform_secret" and not cred_ok:
        raise NoSafeRoute(
            reason_code="provider_secret_missing",
            message=f"모델 '{model_id}'의 Provider 비밀키가 설정되지 않았습니다.",
            upstream_called=False,
        )

    route_id = (
        f"platform:{cm.model_id}" if cred_source == "platform_secret"
        else f"openrouter:{cm.model_id}"
    )

    fallback_candidates: list[dict[str, str]] = []
    if allow_external_fallback:
        all_models = get_catalog_models()
        fallback_candidates = [
            {
                "model_id": m.model_id,
                "upstream_model": m.upstream_model,
                "provider": m.provider,
                "route_id": (
                    f"platform:{m.model_id}"
                    if m.credential_source == "platform_secret"
                    else f"openrouter:{m.model_id}"
                ),
                "reason": "catalog_alternative",
            }
            for m in all_models
            if m.model_id != model_id
        ][:3]  # limit to top 3 fallback candidates

    reason_codes = ["manual_selection"]
    if not allow_external_fallback:
        reason_codes.append("external_fallback_disabled")

    return RouteDecision(
        route_mode=RouteMode.MANUAL.value,
        selected_provider=cm.provider,
        selected_model=cm.model_id,
        selected_upstream_model=cm.upstream_model,
        selected_route_id=route_id,
        reason_codes=reason_codes,
        fallback_allowed=allow_external_fallback,
        eligible_fallback=fallback_candidates,
        excluded_candidates=[],
        credential_available=cred_ok,
        credential_status=cred_status,
        evidence_status=EvidenceStatus.RESOLVED_NOT_CALLED.value,
        request_id=request_id,
        provider_mode=openrouter_config.provider_mode,
        max_attempts=1 if not allow_external_fallback else min(1 + len(fallback_candidates), 3),
        credential_source=cred_source,
        platform_provider_id=plat_pid,
    )


def resolve_auto_route(
    task_type: str = "general",
    required_capabilities: list[str] | None = None,
    optimize_for: str = "balanced",
    allow_external_fallback: bool = True,
    provider_order: list[str] | None = None,
    max_attempts: int | None = None,
) -> RouteDecision:
    """Resolve an automatic route for b14/auto.

    Uses catalog metadata to deterministically select the best model.
    Does NOT make upstream calls.

    Hard constraints (applied first):
    - Model must be enabled
    - Model must have all required_capabilities
    - task_type capability requirements (TASK_TYPE_REQUIRED_CAPABILITIES)

    Preferences (applied second, all enforced):
    - provider_order: listed providers win in the given order
    - optimize_for: balanced | cost | latency | korean
    - task_type "korean": korean_score becomes the leading scoring key

    allow_external_fallback=False is enforced: no fallback candidates and
    exactly one attempt.

    Returns RouteDecision. Raises NoSafeRoute if no candidate is found.
    """
    request_id = _new_request_id()

    raw_candidates = _filter_catalog(
        required_capabilities=required_capabilities,
        task_type=task_type,
    )

    excluded: list[dict[str, str]] = []
    secret_missing_ids: set[str] = set()

    all_models = get_catalog_models()
    candidates = []
    for m in all_models:
        if m in raw_candidates:
            if m.credential_source == "platform_secret" and not _platform_secret_present(m):
                secret_missing_ids.add(m.model_id)
                continue
            candidates.append(m)
        else:
            excluded.append({
                "model_id": m.model_id,
                "upstream_model": m.upstream_model,
                "provider": m.provider,
                "reason": "capability_mismatch",
            })
    for m in all_models:
        if m.model_id in secret_missing_ids:
            excluded.append({
                "model_id": m.model_id,
                "upstream_model": m.upstream_model,
                "provider": m.provider,
                "reason": "provider_secret_missing",
            })

    if not candidates:
        raise NoSafeRoute(
            reason_code="no_candidate_meets_capabilities",
            message="요구사항을 충족하는 모델이 없습니다. required_capabilities 또는 optimize_for를 확인하십시오.",
            upstream_called=False,
        )

    sorted_candidates = select_by_optimize(
        candidates,
        optimize_for,
        allow_external_fallback,
        provider_order=provider_order,
        task_type=task_type,
    )
    selected = sorted_candidates[0]
    cred_ok, cred_status, cred_source, plat_pid = _credential_status_for(selected)
    route_id = (
        f"platform:{selected.model_id}" if cred_source == "platform_secret"
        else f"openrouter:{selected.model_id}"
    )

    if allow_external_fallback:
        fallback_candidates = [
            {
                "model_id": m.model_id,
                "upstream_model": m.upstream_model,
                "provider": m.provider,
                "route_id": (
                    f"platform:{m.model_id}"
                    if m.credential_source == "platform_secret"
                    else f"openrouter:{m.model_id}"
                ),
                "reason": "auto_fallback_candidate",
            }
            for m in sorted_candidates[1:]
        ]
        effective_max_attempts = max_attempts or min(len(sorted_candidates), 3)
    else:
        fallback_candidates = []
        effective_max_attempts = 1

    reason_codes = [f"optimize_for:{optimize_for}", f"task_type:{task_type}"]
    if required_capabilities:
        reason_codes.append(f"capabilities:{','.join(required_capabilities)}")
    if provider_order:
        reason_codes.append(f"provider_order:{','.join(provider_order)}")
    if not allow_external_fallback:
        reason_codes.append("external_fallback_disabled")
    reason_codes.append(f"selected:{selected.model_id}")

    return RouteDecision(
        route_mode=RouteMode.AUTO.value,
        selected_provider=selected.provider,
        selected_model=selected.model_id,
        selected_upstream_model=selected.upstream_model,
        selected_route_id=route_id,
        reason_codes=reason_codes,
        fallback_allowed=allow_external_fallback,
        eligible_fallback=fallback_candidates,
        excluded_candidates=excluded,
        credential_available=cred_ok,
        credential_status=cred_status,
        evidence_status=EvidenceStatus.RESOLVED_NOT_CALLED.value,
        request_id=request_id,
        provider_mode=openrouter_config.provider_mode,
        max_attempts=effective_max_attempts,
        credential_source=cred_source,
        platform_provider_id=plat_pid,
    )


def resolve_route(model_id: str, business14_options: dict[str, Any] | None = None) -> RouteDecision:
    """Resolve any route (manual or auto) without making upstream calls.

    - If model_id == "b14/auto": use automatic routing
    - Otherwise: use manual routing with the specific model_id

    Returns RouteDecision. Raises NoSafeRoute if routing fails.
    """
    opts = business14_options or {}

    if model_id.strip() == "b14/auto":
        allow_external_fallback = opts.get("allow_external_fallback", True)
        return resolve_auto_route(
            task_type=opts.get("task_type", "general"),
            required_capabilities=opts.get("required_capabilities") or ["chat"],
            optimize_for=opts.get("optimize_for", "balanced"),
            allow_external_fallback=allow_external_fallback,
            provider_order=opts.get("provider_order"),
            max_attempts=opts.get("max_attempts"),
        )

    allow_external_fallback = opts.get("allow_external_fallback", False)
    return resolve_manual_route(
        model_id,
        allow_external_fallback=allow_external_fallback,
    )


# Error classes for fallback logic
class RoutingError(Exception):
    """Raised when routing cannot be completed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# Fallback-allowable error codes:
# transport failure, timeout, HTTP 429, HTTP 5xx ONLY.
_FALLBACK_ALLOWED_CODES = frozenset({
    "upstream_timeout",
    "upstream_server_error",
    "upstream_rate_limited",
})

# Fallback-prohibited error codes:
# HTTP 400/401/403/404/409/422/any other 4xx, malformed request,
# malformed upstream response, oversize response, missing key,
# unsupported feature, internal errors.
_FALLBACK_PROHIBITED_CODES = frozenset({
    "upstream_auth_failed",
    "upstream_client_error",
    "malformed_upstream_response",
    "upstream_response_too_large",
    "missing_provider_key",
    "placeholder_key_rejected",
    "invalid_body",
    "invalid_request",
    "model_not_found",
    "model_disabled",
    "unsupported_model",
    "pilot_not_configured",
    "no_safe_route",
    "internal_error",
})


def is_error_fallback_allowed(code: str) -> bool:
    """Return True if an error code permits fallback to another candidate.

    Anything not explicitly allowed is prohibited (fail closed).
    """
    if code in _FALLBACK_ALLOWED_CODES:
        return True
    return False
