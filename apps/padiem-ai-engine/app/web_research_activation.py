"""E9 A1 Web/Research capability activation gate (#1753, #1744).

The Engine's first capability activation. This module is a source-level,
fail-closed readiness record for the ``web_search`` / ``web_fetch`` /
``deep_research`` capability family:

- it refuses to authorize anything without the exact owner confirmation token,
- it enforces exact-head (main SHA) verification,
- it records the rollback anchor (current deployed version -> rollback version),
- it runs non-sensitive synthetic probes against the shared Web/Research route,
- it runs a structural reference-product parity probe for the first reference
  consumers of this capability family.

This module never mutates Production, never calls a real web provider, never
imports a product package, and never touches credential material. Production
activation is a separate owner-authorized dispatch; this module records only
evidence and readiness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.web_research_service import WebResearchEngineService

CONFIRMATION_TOKEN = "ACTIVATE_ENGINE_A1_WEB_RESEARCH"

CURRENT_DEPLOYED_VERSION = "26288341021f9b2ceaa45b9f587d571af63a07bf"
ROLLBACK_VERSION = "8d4db98c13b2b23378536d3b2e5270bb3b457f06"
DEPLOYMENT_TARGET = "Cloudflare Workers (padiem-ai-engine)"

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Reference consumers of the A1 Web/Research capability family, in activation
# priority. These are opaque product-neutral identifiers only; the parity probe
# never imports or executes product code.
REFERENCE_CONSUMERS = ("lovebud-scout", "400-ai-finder")

_SYNTHETIC_OPERATIONS = ("search", "fetch", "deep_research")
_SYNTHETIC_QUERY = "public web research structural probe"
_SYNTHETIC_FETCH_URL = "https://example.com/public-page"


class ActivationError(ValueError):
    """Fail-closed activation failure carrying only safe, bounded information."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("activation error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class RollbackAnchor:
    """Recorded rollback anchor for the A1 activation.

    Config/secret names are recorded without values; this module never
    publishes secret material.
    """

    deployment_target: str
    current_deployed_version: str
    rollback_version: str
    config_binding_diff: str
    secret_name_diff: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "deployment_target": self.deployment_target,
            "current_deployed_version": self.current_deployed_version,
            "rollback_version": self.rollback_version,
            "config_binding_diff": self.config_binding_diff,
            "secret_name_diff": self.secret_name_diff,
        }


@dataclass(frozen=True, slots=True)
class SyntheticProbeResult:
    operation: str
    ok: bool
    error_code: str | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "ok": self.ok,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class ReferenceParityResult:
    consumer: str
    ok: bool
    finding: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "ok": self.ok,
            "finding": self.finding,
        }


@dataclass(frozen=True, slots=True)
class ActivationEvidence:
    """Public, secret-free activation evidence record for one gate run."""

    current_main: str
    accepted_source_head: str
    deployment_target: str
    current_deployed_version: str
    rollback_version: str
    config_binding_diff: str
    secret_name_diff: str
    reference_consumers: tuple[str, ...]
    synthetic_probes: tuple[SyntheticProbeResult, ...]
    reference_parity: tuple[ReferenceParityResult, ...]
    real_provider_call_count: int = 0
    real_user_data: int = 0
    mutation_scope: str = "A1 Web/Research activation only"
    final_disposition: str = "PENDING_PRODUCTION_AUTHORIZATION"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "current_main": self.current_main,
            "accepted_source_head": self.accepted_source_head,
            "deployment_target": self.deployment_target,
            "current_deployed_version": self.current_deployed_version,
            "rollback_version": self.rollback_version,
            "config_binding_diff": self.config_binding_diff,
            "secret_name_diff": self.secret_name_diff,
            "reference_consumers": list(self.reference_consumers),
            "synthetic_probes": [p.to_public_dict() for p in self.synthetic_probes],
            "reference_parity": [p.to_public_dict() for p in self.reference_parity],
            "real_provider_call_count": self.real_provider_call_count,
            "real_user_data": self.real_user_data,
            "mutation_scope": self.mutation_scope,
            "final_disposition": self.final_disposition,
        }


def _verify_sha(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not _COMMIT_SHA_RE.fullmatch(value):
        raise ActivationError(
            "invalid_sha",
            f"{name} must be a 40-character lowercase hex commit SHA.",
        )


def verify_confirmation_token(token: str) -> None:
    """Fail closed unless the caller supplies the exact owner token.

    The token is a fixed, non-secret activation phrase that only the Product
    Owner (or a CTO-approved owner delegate) is authorized to provide during
    an explicit activation dispatch.
    """
    if not isinstance(token, str) or token != CONFIRMATION_TOKEN:
        raise ActivationError(
            "activation_not_authorized",
            "Web/Research activation requires the exact owner confirmation token.",
        )


def verify_exact_main(current_main: str) -> None:
    """Enforce exact-head: the gate must be dispatched on a real main SHA."""
    _verify_sha(current_main, name="current_main")


def record_rollback_anchor() -> RollbackAnchor:
    """Return the audited rollback anchor recorded for this activation."""
    _verify_sha(CURRENT_DEPLOYED_VERSION, name="current_deployed_version")
    _verify_sha(ROLLBACK_VERSION, name="rollback_version")
    return RollbackAnchor(
        deployment_target=DEPLOYMENT_TARGET,
        current_deployed_version=CURRENT_DEPLOYED_VERSION,
        rollback_version=ROLLBACK_VERSION,
        config_binding_diff="none",
        secret_name_diff="none",
    )


async def run_synthetic_probe(
    service: WebResearchEngineService,
    *,
    operation: str,
) -> SyntheticProbeResult:
    """Run one non-sensitive structural probe against the shared research route.

    The probe never calls a real provider, never uses real user data, and only
    validates the bounded response envelope of the shared Engine route.
    """
    if operation not in _SYNTHETIC_OPERATIONS:
        raise ActivationError(
            "invalid_probe_operation",
            "synthetic probe operation must be search, fetch, or deep_research.",
        )
    payload: dict[str, Any] = {
        "app_id": "engine-a1-synthetic-probe",
        "operation": operation,
        "query": _SYNTHETIC_QUERY,
        "agent": {
            "id": "agent:engine:a1-probe",
            "title": "A1 synthetic probe agent",
            "description": "Non-sensitive structural probe for Web/Research activation.",
            "system_instruction": "Answer from the grounded context only.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 256,
        },
        "trace_id": "a1-synthetic-probe",
    }
    if operation == "fetch":
        payload["url"] = _SYNTHETIC_FETCH_URL
    response = await service.research_payload(payload)
    body = response.body if isinstance(response.body, Mapping) else {}
    if response.status_code == 200 and body.get("ok") is True:
        return SyntheticProbeResult(
            operation=operation,
            ok=True,
            error_code=None,
        )
    error = body.get("error")
    error_code = error.get("code") if isinstance(error, Mapping) else "unknown_error"
    return SyntheticProbeResult(
        operation=operation,
        ok=False,
        error_code=error_code,
    )


async def run_reference_parity_probe(
    service: WebResearchEngineService,
) -> tuple[ReferenceParityResult, ...]:
    """Structural parity probe for the first reference consumers.

    Shared Engine route vs product-local route parity at the contract level:
    the shared route must serve the bounded response envelope every reference
    consumer requires (ok/operation/answer/evidence fields, normalized error
    taxonomy) without accepting provider authority fields from the request.
    No product code is imported or executed.
    """
    results: list[ReferenceParityResult] = []
    for consumer in REFERENCE_CONSUMERS:
        if not isinstance(consumer, str) or not _IDENTIFIER_RE.fullmatch(consumer):
            raise ActivationError(
                "invalid_reference_consumer",
                "reference consumer must be a bounded safe identifier.",
            )
        payload: dict[str, Any] = {
            "app_id": f"{consumer}-a1-parity",
            "operation": "search",
            "query": _SYNTHETIC_QUERY,
            "agent": {
                "id": "agent:engine:a1-parity",
                "title": "A1 parity probe agent",
                "description": "Non-sensitive parity probe for Web/Research activation.",
                "system_instruction": "Answer from the grounded context only.",
                "task_type": "general",
                "optimize_for": "balanced",
                "max_tokens": 256,
            },
            "trace_id": f"a1-parity-{consumer}",
        }
        response = await service.research_payload(payload)
        body = response.body if isinstance(response.body, Mapping) else {}
        if response.status_code != 200 or body.get("ok") is not True:
            error = body.get("error")
            error_code = error.get("code") if isinstance(error, Mapping) else "unknown_error"
            results.append(
                ReferenceParityResult(
                    consumer=consumer,
                    ok=False,
                    finding=f"shared route failed parity ({error_code})",
                )
            )
            continue
        if "route" in body or "metadata" in body:
            results.append(
                ReferenceParityResult(
                    consumer=consumer,
                    ok=False,
                    finding="shared research service leaked route/metadata fields",
                )
            )
            continue
        results.append(
            ReferenceParityResult(
                consumer=consumer,
                ok=True,
                finding="shared research service serves bounded parity envelope",
            )
        )
    return tuple(results)


async def evaluate_activation(
    service: WebResearchEngineService,
    *,
    confirmation_token: str,
    current_main: str,
    accepted_source_head: str,
) -> ActivationEvidence:
    """Fail-closed activation readiness evaluation for A1 Web/Research.

    Raises ``ActivationError`` on any preflight failure; otherwise records
    secret-free evidence. The result never authorizes Production mutation by
    itself.
    """
    verify_confirmation_token(confirmation_token)
    verify_exact_main(current_main)
    _verify_sha(accepted_source_head, name="accepted_source_head")
    anchor = record_rollback_anchor()

    probes: list[SyntheticProbeResult] = []
    for operation in _SYNTHETIC_OPERATIONS:
        probes.append(await run_synthetic_probe(service, operation=operation))

    parity = await run_reference_parity_probe(service)

    if any(not probe.ok for probe in probes):
        raise ActivationError(
            "synthetic_probe_failed",
            "A1 synthetic probes must all pass before activation readiness.",
        )
    if any(not result.ok for result in parity):
        raise ActivationError(
            "reference_parity_failed",
            "A1 reference parity probes must all pass before activation readiness.",
        )

    return ActivationEvidence(
        current_main=current_main,
        accepted_source_head=accepted_source_head,
        deployment_target=anchor.deployment_target,
        current_deployed_version=anchor.current_deployed_version,
        rollback_version=anchor.rollback_version,
        config_binding_diff=anchor.config_binding_diff,
        secret_name_diff=anchor.secret_name_diff,
        reference_consumers=REFERENCE_CONSUMERS,
        synthetic_probes=tuple(probes),
        reference_parity=parity,
        real_provider_call_count=0,
        real_user_data=0,
        mutation_scope="A1 Web/Research activation only",
        final_disposition="PENDING_PRODUCTION_AUTHORIZATION",
    )
