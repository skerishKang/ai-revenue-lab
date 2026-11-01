"""Router Core for Business 14 Alpha.

Implements manual routing with deterministic model selection, fallback
logic, and no-safe-route handling.

Manual:
  - Specific catalog model ID → single upstream call
  - No provider switching unless explicit
  - The owner-selected free-tier primary with a trusted product grade
    receives exactly one preselected grade fallback (tier_fallback);
    no other route offers catalog substitutions (#2085 no-auto policy).
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
from app.pilot.owner_model_exclusions import (
    excluded_from_owner_customer_selection,
    free_candidate_excluded_from_execution,
)
from app.pilot.errors import NoSafeRoute, RoutingError


class RouteMode(str, enum.Enum):
    MANUAL = "manual"


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
    # There is no attempt limit here. The number of candidates one dispatch
    # may try is the number of candidates the declared product grade allows:
    # the selected model plus ``eligible_fallback``. B14 walks that list in
    # order, advances only on a recoverable provider error, visits each
    # candidate once, and stops when the list is exhausted (#4317).
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
    product_tier: str = "free",
) -> RouteDecision:
    """Resolve a manual route for a specific model ID.

    Returns a RouteDecision. Does NOT make upstream calls.
    Raises NoSafeRoute if the model is not in the catalog or is disabled.

    Manual routes default to no arbitrary catalog substitutions. An owner-
    selected primary with trusted product grade instead receives
    exactly one preselected grade fallback on recoverable provider failure.

    The number of candidates this route may try is the number of candidates
    it allows: the selected model plus its eligible fallback list. No separate
    attempt count narrows that list, so a grade with more allowed candidates
    is tried in full without any numeric ceiling to maintain (#4317).
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
    # #2505 (owner decision 2026-10-21): an excluded free candidate is never
    # an execution candidate, so a customer that sends the exact id, or a
    # resolver that answers with it, gets no route at all.
    if free_candidate_excluded_from_execution(model_id):
        raise NoSafeRoute(
            reason_code="free_candidate_excluded",
            message="제외된 무료 모델은 실행할 수 없습니다.",
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
    # paid model; external fallback is not offered to any manual route.
    cred_ok, cred_status, cred_source, plat_pid = _credential_status_for(cm)

    # Platform-owned secret missing -> fail closed with zero upstream calls.
    if cred_source == "platform_secret" and not cred_ok:
        from app.pilot import platform_secrets as ps

        raise NoSafeRoute(
            reason_code="provider_secret_missing",
            message=f"모델 '{model_id}'의 Provider 비밀키가 설정되지 않았습니다.",
            upstream_called=False,
            credential_reason=ps.credential_failure_reason(
                ps.get_platform_provider(plat_pid)
            ),
        )

    route_id = f"platform:{cm.model_id}"

    from .tier_fallback import TIER_DEFAULT_B14_MODEL
    owner_tier_pair = product_tier == "free" and model_id == TIER_DEFAULT_B14_MODEL
    fallback_candidates: list[dict[str, str]] = []
    if owner_tier_pair:
        from .tier_fallback import TIER_FALLBACK_B14_MODELS
        if product_tier not in TIER_FALLBACK_B14_MODELS:
            raise NoSafeRoute(reason_code="invalid_product_tier", message="Unsupported product tier.", upstream_called=False)
        for candidate_id in TIER_FALLBACK_B14_MODELS[product_tier]:
            target = get_catalog_by_id(candidate_id)
            if target is not None and target.enabled and not excluded_from_owner_customer_selection(target.model_id) and not free_candidate_excluded_from_execution(target.model_id) and _platform_secret_present(target):
                fallback_candidates.append({
                    "model_id": target.model_id,
                    "upstream_model": target.upstream_model,
                    "provider": target.provider,
                    "platform_provider_id": target.platform_provider_id,
                    "route_id": f"platform:{target.model_id}",
                    "reason": "owner_selected_tier_fallback",
                })

    reason_codes = ["manual_selection"]
    if owner_tier_pair:
        reason_codes.append("owner_selected_tier_fallback:" + product_tier)

    return RouteDecision(
        route_mode=RouteMode.MANUAL.value,
        selected_provider=cm.provider,
        selected_model=cm.model_id,
        selected_upstream_model=cm.upstream_model,
        selected_route_id=route_id,
        reason_codes=reason_codes,
        fallback_allowed=bool(fallback_candidates),
        eligible_fallback=fallback_candidates,
        excluded_candidates=[],
        credential_available=cred_ok,
        credential_status=cred_status,
        evidence_status=EvidenceStatus.RESOLVED_NOT_CALLED.value,
        request_id=request_id,
        provider_mode=runtime_config.provider_mode,
        credential_source=cred_source,
        platform_provider_id=plat_pid,
    )




def resolve_route(model_id: str, business14_options: dict[str, Any] | None = None) -> RouteDecision:
    """Resolve a manual route without making upstream calls.

    There is no automatic route of any kind: every resolved route is manual,
    and an id outside the registered catalog is refused by the ordinary
    unknown-model handling.

    Returns RouteDecision. Raises NoSafeRoute if routing fails.
    """
    opts = business14_options or {}

    return resolve_manual_route(
        model_id,
        product_tier=opts.get("product_tier", "free"),
    )


# Fallback-allowable error codes:
# transport failure, timeout, HTTP 429/5xx and unreadable provider responses.
_FALLBACK_ALLOWED_CODES = frozenset({
    "upstream_timeout",
    "malformed_upstream_response",
    "upstream_server_error",
    "upstream_rate_limited",
})

# Fallback-prohibited error codes:
# HTTP 400/401/403/404/409/422/any other 4xx, malformed request,
# oversize response, missing key,
# unsupported feature, internal errors.
_FALLBACK_PROHIBITED_CODES = frozenset({
    "upstream_auth_failed",
    "upstream_client_error",
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


def is_error_fallback_allowed(code: str, *, reason: str | None = None) -> bool:
    """Return True if an error code permits fallback to another candidate.

    Anything not explicitly allowed is prohibited (fail closed).
    """
    # HTTP 400 has a legacy malformed code. Preserve its no-fallback rule
    # without changing the external error/attempt schema for rejected input.
    if reason in {"upstream_http_400", "unexpected_http_status"}:
        return False
    if code in _FALLBACK_ALLOWED_CODES:
        return True
    return False
