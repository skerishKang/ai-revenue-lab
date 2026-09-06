"""Versioned capability manifest for Padiem AI Engine (#1752 E8).

The Engine exposes one truthful, fail-closed capability ledger that every
first-party product integration (B30, B53, B54, B61, B62, LoveBud Scout and
any future consumer) can require before it routes work to the Engine.

Rules that keep the manifest honest:

* A capability is ``AVAILABLE`` only when the route the capability names
  actually consumes it with the Engine's bounded trust/authority semantics
  (B14 provider authority, caller/application scope, Core reuse).
* A ``DEFERRED`` capability has a real source seam but is not Production
  activated: its trusted authority is either not wired, not provisioned, or
  env-gated. It cannot be required.
* An ``UNAVAILABLE`` capability is not offered at all by this contract
  version.
* ``require_capability`` fails closed: a DEFERRED/UNAVAILABLE/unknown
  capability or an incompatible major never silently degrades.
* The public dict exposes no provider inventory, credential material, or
  product identity; the per-capability scope matrix is the only public
  authority claim.

This module intentionally does not import worker composition roots; the
conformance suite cross-checks manifest state against the routed service
truth (including fail-closed behavior) independently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .agent_skill_service import (
    AGENT_SKILL_CANCEL_PATH,
    AGENT_SKILL_RESUME_PATH,
    AGENT_SKILL_RUN_PATH,
)
from .document_context_service import DOCUMENT_CONTEXT_PATH
from .memory_service import MEMORY_PATH, MEMORY_WRITE_PATH
from .multimodal_attachment_service import MULTIMODAL_EXECUTE_PATH
from .orchestration_service import (
    ORCHESTRATE_CANCEL_PATH,
    ORCHESTRATE_PATH,
    ORCHESTRATE_RESUME_PATH,
    ORCHESTRATION_STREAM_PATH,
)
from .service import EXECUTE_PATH
from .streaming_service import STREAM_PATH
from .tool_projection import TOOL_CANCEL_PATH, TOOL_EXECUTE_PATH, TOOL_RESUME_PATH
from .web_research_service import RESEARCH_PATH

CAPABILITY_FAMILY = "padiem-ai-engine"
CAPABILITY_MAJOR = 1
CAPABILITY_VERSION = "1.0"

# The E8 acceptance scope: the product-neutral capability set every reference
# product integration must be able to require.
REQUIRED_CAPABILITY_IDS = frozenset(
    {
        "completed_execution",
        "streaming_execution",
        "orchestration",
        "continuation/approval",
        "multi_caller_identity",
        "web_search",
        "web_fetch",
        "deep_research",
        "evidence_citations",
        "tool_runtime",
        "memory_rag",
        "agent_skill_runtime",
        "file_document_multimodal",
        "tenant_entitlement_usage_admission",
        "idempotency",
    }
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_BOUNDED_STATE = frozenset({"bounded"})
_PRESERVED_OR_NA = frozenset({"preserved", "n/a"})


class CapabilityManifestError(ValueError):
    """Fail-closed manifest failure carrying only safe, bounded information."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("capability error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class CapabilityState(str, Enum):
    AVAILABLE = "available"
    DEFERRED = "deferred"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CapabilityScopeRow:
    """One acceptance-matrix row shared by every capability declaration."""

    caller_identity: str = "bounded"
    app_scope: str = "bounded"
    tenant_scope: str | None = None
    input_bounds: str = "enforced"
    authority_widening: int = 0
    core_semantics_reused: str = "yes"
    b14_provider_authority: str = "n/a"
    error_taxonomy: str = "normalized"
    stream_final_parity: str = "n/a"
    cancellation_timeout: str = "n/a"
    private_data_leakage: int = 0
    product_specific_engine_branch: int = 0

    def __post_init__(self) -> None:
        if self.caller_identity not in _BOUNDED_STATE:
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "caller_identity must be bounded",
            )
        if self.app_scope not in _BOUNDED_STATE:
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "app_scope must be bounded",
            )
        if self.tenant_scope is not None and self.tenant_scope not in _BOUNDED_STATE:
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "tenant_scope must be bounded or absent",
            )
        if self.input_bounds != "enforced":
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "input_bounds must be enforced",
            )
        if self.authority_widening != 0:
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "authority_widening must be zero",
            )
        if self.core_semantics_reused != "yes":
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "core_semantics_reused must be yes",
            )
        if self.b14_provider_authority not in _PRESERVED_OR_NA:
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "b14_provider_authority must be preserved or n/a",
            )
        if self.error_taxonomy != "normalized":
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "error_taxonomy must be normalized",
            )
        if self.stream_final_parity not in {"pass", "n/a"}:
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "stream_final_parity must be pass or n/a",
            )
        if self.cancellation_timeout not in {"preserved", "n/a"}:
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "cancellation_timeout must be preserved or n/a",
            )
        if self.private_data_leakage != 0:
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "private_data_leakage must be zero",
            )
        if self.product_specific_engine_branch != 0:
            raise CapabilityManifestError(
                "invalid_capability_matrix",
                "product_specific_engine_branch must be zero",
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "caller_identity": self.caller_identity,
            "app_scope": self.app_scope,
            "tenant_scope": self.tenant_scope,
            "input_bounds": self.input_bounds,
            "authority_widening": self.authority_widening,
            "core_semantics_reused": self.core_semantics_reused,
            "b14_provider_authority": self.b14_provider_authority,
            "error_taxonomy": self.error_taxonomy,
            "stream_final_parity": self.stream_final_parity,
            "cancellation_timeout": self.cancellation_timeout,
            "private_data_leakage": self.private_data_leakage,
            "product_specific_engine_branch": self.product_specific_engine_branch,
        }


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    id: str
    state: CapabilityState
    routes: tuple[str, ...]
    scope: CapabilityScopeRow

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _IDENTIFIER_RE.fullmatch(self.id):
            raise CapabilityManifestError(
                "invalid_capability",
                "capability id must be a bounded safe identifier",
            )
        if not isinstance(self.state, CapabilityState):
            raise CapabilityManifestError(
                "invalid_capability",
                "capability state must be CapabilityState",
            )
        if isinstance(self.routes, (str, bytes)) or not isinstance(self.routes, tuple):
            raise CapabilityManifestError(
                "invalid_capability",
                "capability routes must be a tuple of internal Engine paths",
            )
        if any(
            not isinstance(path, str) or not path.startswith("/internal/v1/")
            for path in self.routes
        ):
            raise CapabilityManifestError(
                "invalid_capability",
                "capability routes must be internal Engine paths",
            )
        if len(set(self.routes)) != len(self.routes):
            raise CapabilityManifestError(
                "invalid_capability",
                "capability routes must be unique",
            )
        if not isinstance(self.scope, CapabilityScopeRow):
            raise CapabilityManifestError(
                "invalid_capability",
                "capability scope must be CapabilityScopeRow",
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "state": self.state.value,
            "routes": list(self.routes),
            "scope": self.scope.to_public_dict(),
        }


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    family: str
    major: int
    version: str
    capabilities: tuple[CapabilityDeclaration, ...]

    def __post_init__(self) -> None:
        if (
            self.family != CAPABILITY_FAMILY
            or self.major != CAPABILITY_MAJOR
            or self.version != CAPABILITY_VERSION
        ):
            raise CapabilityManifestError(
                "invalid_capability_manifest",
                "capability manifest identity is invalid",
            )
        if not isinstance(self.capabilities, tuple) or not self.capabilities:
            raise CapabilityManifestError(
                "invalid_capability_manifest",
                "capabilities must be a non-empty tuple",
            )
        if any(
            not isinstance(item, CapabilityDeclaration) for item in self.capabilities
        ):
            raise CapabilityManifestError(
                "invalid_capability_manifest",
                "capabilities contain an invalid value",
            )
        capability_ids = tuple(item.id for item in self.capabilities)
        if len(set(capability_ids)) != len(capability_ids):
            raise CapabilityManifestError(
                "invalid_capability_manifest",
                "capability ids must be unique",
            )
        missing = REQUIRED_CAPABILITY_IDS - set(capability_ids)
        if missing:
            raise CapabilityManifestError(
                "invalid_capability_manifest",
                "capability manifest omits required capability ids",
            )

    def capability_state(self, capability_id: str) -> CapabilityState:
        if not isinstance(capability_id, str) or not _IDENTIFIER_RE.fullmatch(
            capability_id
        ):
            raise CapabilityManifestError(
                "invalid_capability",
                "capability_id must be a bounded safe identifier",
            )
        for item in self.capabilities:
            if item.id == capability_id:
                return item.state
        raise CapabilityManifestError(
            "unknown_capability",
            "Engine capability is not declared by this manifest version",
        )

    def require_capability(
        self,
        capability_id: str,
        *,
        requested_major: int = CAPABILITY_MAJOR,
    ) -> CapabilityDeclaration:
        if isinstance(requested_major, bool) or not isinstance(requested_major, int):
            raise CapabilityManifestError(
                "invalid_capability_version",
                "requested_major must be an integer",
            )
        if requested_major != self.major:
            raise CapabilityManifestError(
                "incompatible_capability",
                "requested capability major is not supported",
            )
        declaration = None
        for item in self.capabilities:
            if item.id == capability_id:
                declaration = item
                break
        if declaration is None:
            raise CapabilityManifestError(
                "unknown_capability",
                "Engine capability is not declared by this manifest version",
            )
        if declaration.state is not CapabilityState.AVAILABLE:
            raise CapabilityManifestError(
                "capability_unavailable",
                "required Engine capability is not available in this manifest version",
            )
        return declaration

    def to_public_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "major": self.major,
            "version": self.version,
            "capabilities": [item.to_public_dict() for item in self.capabilities],
        }


def _row(**overrides: object) -> CapabilityScopeRow:
    base = {
        "caller_identity": "bounded",
        "app_scope": "bounded",
        "tenant_scope": None,
        "input_bounds": "enforced",
        "authority_widening": 0,
        "core_semantics_reused": "yes",
        "b14_provider_authority": "n/a",
        "error_taxonomy": "normalized",
        "stream_final_parity": "n/a",
        "cancellation_timeout": "n/a",
        "private_data_leakage": 0,
        "product_specific_engine_branch": 0,
    }
    base.update(overrides)
    return CapabilityScopeRow(**base)


def current_capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        family=CAPABILITY_FAMILY,
        major=CAPABILITY_MAJOR,
        version=CAPABILITY_VERSION,
        capabilities=(
            CapabilityDeclaration(
                id="completed_execution",
                state=CapabilityState.AVAILABLE,
                routes=(EXECUTE_PATH,),
                scope=_row(b14_provider_authority="preserved"),
            ),
            CapabilityDeclaration(
                id="streaming_execution",
                state=CapabilityState.AVAILABLE,
                routes=(STREAM_PATH,),
                scope=_row(
                    b14_provider_authority="preserved",
                    stream_final_parity="pass",
                ),
            ),
            CapabilityDeclaration(
                id="orchestration",
                state=CapabilityState.AVAILABLE,
                routes=(
                    ORCHESTRATE_PATH,
                    ORCHESTRATE_RESUME_PATH,
                    ORCHESTRATE_CANCEL_PATH,
                    ORCHESTRATION_STREAM_PATH,
                ),
                scope=_row(
                    tenant_scope="bounded",
                    b14_provider_authority="preserved",
                    cancellation_timeout="preserved",
                ),
            ),
            CapabilityDeclaration(
                id="continuation/approval",
                state=CapabilityState.DEFERRED,
                routes=(ORCHESTRATE_RESUME_PATH,),
                scope=_row(
                    tenant_scope="bounded",
                    b14_provider_authority="preserved",
                    cancellation_timeout="preserved",
                ),
            ),
            CapabilityDeclaration(
                id="multi_caller_identity",
                state=CapabilityState.AVAILABLE,
                routes=(),
                scope=_row(),
            ),
            # E9 A1 (#1744): web_search/web_fetch/deep_research were flipped
            # AVAILABLE by owner-authorized bounded Production activation
            # dispatch on main ed18a2a8. Owner decision D2 (2026-09-06, WO-7)
            # reverts them to DEFERRED: `wrangler.toml` has no [vars] and no
            # `keep_vars`, so every deploy drops dashboard vars and
            # PADIEM_ENGINE_WEB_PROVIDER cannot be live — the composition
            # (`create_web_provider` with no configured provider) fails closed
            # 503 web_tools_off. Original record preserved in
            # docs/operations/E9_ACTIVATION_PLAN.md §12; rollback anchor in
            # app/web_research_activation.py. Re-activation requires a real
            # provider var/secret in a separate activation PR (E9 gate +
            # WO-2 composition conformance).
            CapabilityDeclaration(
                id="web_search",
                state=CapabilityState.DEFERRED,
                routes=(RESEARCH_PATH,),
                scope=_row(b14_provider_authority="preserved"),
            ),
            CapabilityDeclaration(
                id="web_fetch",
                state=CapabilityState.DEFERRED,
                routes=(RESEARCH_PATH,),
                scope=_row(b14_provider_authority="preserved"),
            ),
            CapabilityDeclaration(
                id="deep_research",
                state=CapabilityState.DEFERRED,
                routes=(RESEARCH_PATH,),
                scope=_row(b14_provider_authority="preserved"),
            ),
            CapabilityDeclaration(
                id="evidence_citations",
                state=CapabilityState.AVAILABLE,
                routes=(EXECUTE_PATH, STREAM_PATH, RESEARCH_PATH),
                scope=_row(
                    b14_provider_authority="preserved",
                    stream_final_parity="pass",
                ),
            ),
            # E9 A3 (#1746): the earlier bounded activation dispatch (main
            # 1f6220d5) flipped this entry AVAILABLE, but the Production
            # composition (worker_identity.py) injects no tool binding
            # resolver, so every request fails closed 503
            # tool_runtime_unavailable. Reverted to DEFERRED per CTO audit
            # 2026-09-06 (SOURCE_PRESENT != AVAILABLE); re-activation requires
            # the WO-2 production composition conformance gate plus a real
            # tool binding resolver in a separately authorized activation PR.
            CapabilityDeclaration(
                id="tool_runtime",
                state=CapabilityState.DEFERRED,
                routes=(TOOL_EXECUTE_PATH, TOOL_RESUME_PATH, TOOL_CANCEL_PATH),
                scope=_row(
                    tenant_scope="bounded",
                    b14_provider_authority="preserved",
                    cancellation_timeout="preserved",
                ),
            ),
            CapabilityDeclaration(
                id="memory_rag",
                state=CapabilityState.DEFERRED,
                routes=(MEMORY_PATH, MEMORY_WRITE_PATH),
                scope=_row(
                    tenant_scope="bounded",
                    b14_provider_authority="preserved",
                ),
            ),
            CapabilityDeclaration(
                id="agent_skill_runtime",
                state=CapabilityState.DEFERRED,
                routes=(
                    AGENT_SKILL_RUN_PATH,
                    AGENT_SKILL_RESUME_PATH,
                    AGENT_SKILL_CANCEL_PATH,
                ),
                scope=_row(
                    b14_provider_authority="preserved",
                    cancellation_timeout="preserved",
                ),
            ),
            CapabilityDeclaration(
                id="file_document_multimodal",
                state=CapabilityState.DEFERRED,
                routes=(MULTIMODAL_EXECUTE_PATH, DOCUMENT_CONTEXT_PATH),
                scope=_row(tenant_scope="bounded"),
            ),
            CapabilityDeclaration(
                id="tenant_entitlement_usage_admission",
                state=CapabilityState.DEFERRED,
                routes=(),
                scope=_row(tenant_scope="bounded"),
            ),
            CapabilityDeclaration(
                id="idempotency",
                state=CapabilityState.DEFERRED,
                routes=(ORCHESTRATE_PATH,),
                scope=_row(
                    tenant_scope="bounded",
                    b14_provider_authority="preserved",
                ),
            ),
            CapabilityDeclaration(
                id="public_browser_api",
                state=CapabilityState.UNAVAILABLE,
                routes=(),
                scope=_row(),
            ),
            CapabilityDeclaration(
                id="provider_selection",
                state=CapabilityState.UNAVAILABLE,
                routes=(),
                scope=_row(),
            ),
        ),
    )


def require_compatible_capability(
    capability_id: str,
    *,
    requested_major: int = CAPABILITY_MAJOR,
) -> CapabilityDeclaration:
    """Fail-closed entry point used by first-party integrations."""
    return current_capability_manifest().require_capability(
        capability_id,
        requested_major=requested_major,
    )
