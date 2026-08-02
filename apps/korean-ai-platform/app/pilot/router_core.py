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
  - No fallback on: malformed request, missing key, HTTP 401/403, unsupported feature, HTTP 4xx

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


def resolve_manual_route(model_id: str) -> RouteDecision:
    """Resolve a manual route for a specific model ID.

    Returns a RouteDecision. Does NOT make upstream calls.
    Raises NoSafeRoute if the model is not in the catalog or is disabled.
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

    cred_ok, cred_status = _check_credentials()
    route_id = f"b14route_{uuid.uuid4().hex[:12]}"

    # Fallback: all other enabled models
    all_models = get_catalog_models()
    fallback_candidates = [
        {
            "model_id": m.model_id,
            "upstream_model": m.upstream_model,
            "provider": m.provider,
            "reason": "catalog_alternative",
        }
        for m in all_models
        if m.model_id != model_id
    ][:3]  # limit to top 3 fallback candidates

    return RouteDecision(
        route_mode=RouteMode.MANUAL.value,
        selected_provider=cm.provider,
        selected_model=cm.model_id,
        selected_upstream_model=cm.upstream_model,
        selected_route_id=route_id,
        reason_codes=["manual_selection"],
        fallback_allowed=True,
        eligible_fallback=fallback_candidates,
        excluded_candidates=[],
        credential_available=cred_ok,
        credential_status=cred_status,
        evidence_status=EvidenceStatus.RESOLVED_NOT_CALLED.value,
        request_id=request_id,
        provider_mode=openrouter_config.provider_mode,
        max_attempts=1,
    )


def resolve_auto_route(
    task_type: str = "general",
    required_capabilities: list[str] | None = None,
    optimize_for: str = "balanced",
    allow_external_fallback: bool = True,
    max_attempts: int | None = None,
) -> RouteDecision:
    """Resolve an automatic route for b14/auto.

    Uses catalog metadata to deterministically select the best model.
    Does NOT make upstream calls.

    Hard constraints (applied first):
    - Model must be enabled
    - Model must have all required_capabilities

    Preferences (applied second):
    - optimize_for: balanced | cost | latency | korean

    Returns RouteDecision. Raises NoSafeRoute if no candidate is found.
    """
    request_id = _new_request_id()
    route_id = f"b14route_{uuid.uuid4().hex[:12]}"

    cred_ok, cred_status = _check_credentials()

    candidates = _filter_catalog(
        required_capabilities=required_capabilities,
        task_type=task_type,
    )

    excluded: list[dict[str, str]] = []

    all_models = get_catalog_models()
    for m in all_models:
        if m not in candidates:
            excluded.append({
                "model_id": m.model_id,
                "upstream_model": m.upstream_model,
                "provider": m.provider,
                "reason": "capability_mismatch",
            })

    if not candidates:
        raise NoSafeRoute(
            reason_code="no_candidate_meets_capabilities",
            message="요구사항을 충족하는 모델이 없습니다. required_capabilities 또는 optimize_for를 확인하십시오.",
            upstream_called=False,
        )

    sorted_candidates = select_by_optimize(candidates, optimize_for, allow_external_fallback)
    selected = sorted_candidates[0]

    # Compute fallback candidates (remaining sorted candidates)
    fallback_candidates = [
        {
            "model_id": m.model_id,
            "upstream_model": m.upstream_model,
            "provider": m.provider,
            "reason": "auto_fallback_candidate",
        }
        for m in sorted_candidates[1:]
    ]

    effective_max_attempts = max_attempts or min(len(sorted_candidates), 3)

    reason_codes = [f"optimize_for:{optimize_for}", f"task_type:{task_type}"]
    if required_capabilities:
        reason_codes.append(f"capabilities:{','.join(required_capabilities)}")
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
    )


def resolve_route(model_id: str, business14_options: dict[str, Any] | None = None) -> RouteDecision:
    """Resolve any route (manual or auto) without making upstream calls.

    - If model_id == "b14/auto": use automatic routing
    - Otherwise: use manual routing with the specific model_id

    Returns RouteDecision. Raises NoSafeRoute if routing fails.
    """
    opts = business14_options or {}

    if model_id.strip() == "b14/auto":
        return resolve_auto_route(
            task_type=opts.get("task_type", "general"),
            required_capabilities=opts.get("required_capabilities") or ["chat"],
            optimize_for=opts.get("optimize_for", "balanced"),
            allow_external_fallback=opts.get("allow_external_fallback", True),
            max_attempts=opts.get("max_attempts"),
        )

    return resolve_manual_route(model_id)


# Error classes for fallback logic
class RoutingError(Exception):
    """Raised when routing cannot be completed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# Fallback-allowable error codes
_FALLBACK_ALLOWED_CODES = frozenset({
    "upstream_timeout",
    "upstream_server_error",
    "upstream_rate_limited",
    "malformed_upstream_response",
})

# Fallback-prohibited error codes
_FALLBACK_PROHIBITED_CODES = frozenset({
    "upstream_auth_failed",
    "missing_provider_key",
    "placeholder_key_rejected",
    "invalid_body",
    "invalid_request",
    "model_not_found",
    "model_disabled",
    "unsupported_model",
    "pilot_not_configured",
    "no_safe_route",
})


def is_error_fallback_allowed(code: str) -> bool:
    """Return True if an error code permits fallback to another candidate."""
    if code in _FALLBACK_ALLOWED_CODES:
        return True
    if code in _FALLBACK_PROHIBITED_CODES:
        return False
    return False
