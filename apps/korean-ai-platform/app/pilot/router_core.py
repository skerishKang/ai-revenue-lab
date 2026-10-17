"""Router Core for Business 14 Alpha.

Implements Manual and Automatic (b14/auto) routing with deterministic
model selection, fallback logic, and no-safe-route handling.

Manual:
  - Specific catalog model ID → single upstream call
  - No provider switching unless explicit

Automatic (D14, #2044):
  - model = "b14/auto"
  - Resolves through the owner-designated fixed chain in
    app.pilot.routing_policy (ROUTING_POLICY_ID = "fixed_chain_v1").
    No scorer is consulted; task_type / required_capabilities /
    optimize_for / provider_order / allow_paid are accepted but ignored
    (recorded as ignored_options in reason_codes).
  - allow_external_fallback=False → one attempt; max_attempts bounds the
    chain walk (capped at the chain length).
  - Fallback on: timeout, transport failure, HTTP 429, HTTP 5xx
  - No fallback on: HTTP 400/401/403/404/409/422/any other 4xx,
    malformed request, malformed upstream response, missing key,
    unsupported feature, oversize response, unknown exceptions

Resolve endpoint does NOT make upstream calls.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.pilot.catalog import (
    get_catalog_by_id,
    get_catalog_models,
)
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.owner_model_exclusions import excluded_from_owner_customer_selection
from app.pilot.errors import NoSafeRoute, RoutingError


class RouteMode(str, enum.Enum):
    MANUAL = "manual"
    AUTO = "auto"
    AUTO_FALLBACK = "auto_fallback"


class EvidenceStatus(str, enum.Enum):
    MOCK_NO_UPSTREAM_CALL = "mock_no_upstream_call"
    LIVE_VERIFIED = "live_verified"
    RESOLVED_NOT_CALLED = "resolved_not_called"
    LIVE_FAILED = "live_failed"


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
    credential_source: str = ""  # platform_secret (OpenRouter retired, D14 #2044)
    platform_provider_id: str = ""


def _new_request_id() -> str:
    return f"b14req_{uuid.uuid4().hex[:12]}"


def _credential_status_for(cm) -> tuple[bool, str, str, str]:
    """Resolve credential availability/status for a catalog model.

    Returns ``(available, status, source, platform_provider_id)``.
    Every routable model is a platform route (``platform_secret`` marker with
    its own Provider binding); any other credential source is a retired
    configuration and fails closed (D14 #2044: the OpenRouter adapter is gone).
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
    raise RoutingError(
        code="unsupported_credential_source",
        message=(
            f"model '{cm.model_id}' uses retired credential source "
            f"'{cm.credential_source}'."
        ),
    )


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
    product_tier: str = "free",
) -> RouteDecision:
    """Resolve a manual route for a specific model ID.

    Returns a RouteDecision. Does NOT make upstream calls.
    Raises NoSafeRoute if the model is not in the catalog or is disabled.

    Manual routes default to no arbitrary catalog substitutions. An owner-
    selected Cat Jam primary with trusted product grade instead receives
    exactly one preselected grade fallback on recoverable provider failure.
    The generic allow_external_fallback flag does not disable this fixed pair.
    """
    request_id = _new_request_id()
    # Owner exclusions override historical B14 registration in live mode.
    # Preserve mock fixture compatibility; this never authorizes a model.
    if runtime_config.is_live and excluded_from_owner_customer_selection(model_id):
        raise NoSafeRoute(
            reason_code="owner_model_excluded",
            message="OWNER가 제외한 모델은 실행할 수 없습니다.",
            upstream_called=False,
        )
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

    # Free-only TokenHarbor routes may never fall back to another provider's
    # paid model, even when a client requests external fallback.
    if cm.platform_provider_id == "tokenharbor" and allow_external_fallback:
        raise NoSafeRoute(
            reason_code="tokenharbor_free_only_fallback_disabled",
            message="TokenHarbor free-only routes do not allow external fallback.",
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

    route_id = f"platform:{cm.model_id}"

    owner_tier_pair = model_id == "opencode-go/beam-free"
    fallback_candidates: list[dict[str, str]] = []
    if owner_tier_pair:
        from .tier_fallback import TIER_FALLBACK_B14_MODELS
        if product_tier not in TIER_FALLBACK_B14_MODELS:
            raise NoSafeRoute(reason_code="invalid_product_tier", message="Unsupported product tier.", upstream_called=False)
        for candidate_id in TIER_FALLBACK_B14_MODELS[product_tier]:
            target = get_catalog_by_id(candidate_id)
            if target is not None and target.enabled and not excluded_from_owner_customer_selection(target.model_id) and _platform_secret_present(target):
                fallback_candidates.append({
                    "model_id": target.model_id,
                    "upstream_model": target.upstream_model,
                    "provider": target.provider,
                    "platform_provider_id": target.platform_provider_id,
                    "route_id": f"platform:{target.model_id}",
                    "reason": "owner_selected_tier_fallback",
                })
    elif allow_external_fallback:
        all_models = get_catalog_models()
        fallback_candidates = [
            {
                "model_id": m.model_id,
                "upstream_model": m.upstream_model,
                "provider": m.provider,
                "route_id": f"platform:{m.model_id}",
                "platform_provider_id": m.platform_provider_id,
                "reason": "catalog_alternative",
            }
            for m in all_models
            if m.model_id != model_id
            and not excluded_from_owner_customer_selection(m.model_id)
            and m.model_id != "experiential/qwen3.8-flash-next-uncensored"
        ][:3]  # limit to top 3 fallback candidates

    reason_codes = ["manual_selection"]
    if owner_tier_pair:
        reason_codes.append("owner_selected_tier_fallback:" + product_tier)
    elif not allow_external_fallback:
        reason_codes.append("external_fallback_disabled")

    return RouteDecision(
        route_mode=RouteMode.MANUAL.value,
        selected_provider=cm.provider,
        selected_model=cm.model_id,
        selected_upstream_model=cm.upstream_model,
        selected_route_id=route_id,
        reason_codes=reason_codes,
        fallback_allowed=bool(fallback_candidates) if owner_tier_pair else allow_external_fallback,
        eligible_fallback=fallback_candidates,
        excluded_candidates=[],
        credential_available=cred_ok,
        credential_status=cred_status,
        evidence_status=EvidenceStatus.RESOLVED_NOT_CALLED.value,
        request_id=request_id,
        provider_mode=runtime_config.provider_mode,
        max_attempts=(1 + len(fallback_candidates)) if owner_tier_pair else (1 if not allow_external_fallback else min(1 + len(fallback_candidates), 3)),
        credential_source=cred_source,
        platform_provider_id=plat_pid,
    )




def resolve_route(model_id: str, business14_options: dict[str, Any] | None = None) -> RouteDecision:
    """Resolve any route (manual or auto) without making upstream calls.

    - If model_id == "b14/auto": use the owner-designated fixed chain
      (app.pilot.routing_policy, D14 #2044)
    - Otherwise: use manual routing with the specific model_id

    Returns RouteDecision. Raises NoSafeRoute if routing fails.
    """
    opts = business14_options or {}

    if model_id.strip() == "b14/auto":
        # D14 (#2044): owner-designated fixed chain, no scorer. Imported
        # lazily because routing_policy depends on this module's types.
        from app.pilot.routing_policy import resolve_chain_route

        allow_external_fallback = opts.get("allow_external_fallback", True)
        return resolve_chain_route(
            allow_external_fallback=allow_external_fallback,
            max_attempts=opts.get("max_attempts"),
            requested_options=opts,
        )

    allow_external_fallback = opts.get("allow_external_fallback", False)
    return resolve_manual_route(
        model_id,
        allow_external_fallback=allow_external_fallback,
        product_tier=opts.get("product_tier", "free"),
    )


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
