"""Product-neutral context permission and knowledge-boundary gate.

This module composes after source-quality/relevance selection (#1308). It does not
rank web evidence, decide whether a source is relevant, or own product-specific
reader/search semantics. Its only authority is deterministic filtering of context
that is already being considered for one model turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Sequence

from .contracts import Evidence
from .source_quality import SourceQualitySelection

MAX_CONTEXT_CANDIDATES = 32
MAX_ALLOWED_CONTEXT = 16
MAX_POLICY_VERSION_CHARS = 64
MAX_CONTEXT_REF_CHARS = 160
MAX_PROVENANCE_ITEMS = 12

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,159}$")


class ContextPermissionError(ValueError):
    """Raised when a context boundary contract is malformed."""


class BoundaryDisposition(str, Enum):
    """Product-neutral outcome before model context assembly."""

    PERMITTED = "permitted"
    INSUFFICIENT_ALLOWED_CONTEXT = "insufficient_allowed_context"
    OUTSIDE_KNOWLEDGE_BOUNDARY = "outside_knowledge_boundary"
    BOUNDARY_UNAVAILABLE = "boundary_unavailable"


class ContextFilterReason(str, Enum):
    """Stable machine-readable filtering reasons."""

    BOUNDARY_UNAVAILABLE = "boundary_unavailable"
    SOURCE_QUALITY_NOT_SELECTED = "source_quality_not_selected"
    USER_SELF_ASSERTED_PERMISSION = "user_self_asserted_permission"
    DENIED_SCOPE = "denied_scope"
    DENIED_RESOURCE = "denied_resource"
    OUTSIDE_ALLOWED_SCOPE = "outside_allowed_scope"
    OUTSIDE_ALLOWED_RESOURCE = "outside_allowed_resource"
    CONTEXT_LIMIT_EXCEEDED = "context_limit_exceeded"


def _safe_ref(name: str, value: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContextPermissionError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized and allow_empty:
        return ""
    if not normalized or len(normalized) > MAX_CONTEXT_REF_CHARS or not _IDENTIFIER_RE.fullmatch(normalized):
        raise ContextPermissionError(f"{name} must be a bounded safe identifier")
    return normalized


def _safe_tuple(name: str, values: Sequence[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ContextPermissionError(f"{name} must be a sequence of strings")
    checked = tuple(_safe_ref(name, item) for item in values)
    if len(set(checked)) != len(checked):
        raise ContextPermissionError(f"{name} must not contain duplicates")
    return checked


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    """A bounded reference to candidate context for one model turn.

    The candidate deliberately carries references/provenance rather than private
    corpus bytes. Products remain responsible for resolving these references into
    prompt text only after this gate has allowed them.
    """

    id: str
    scope_id: str
    resource_ref: str
    evidence: Evidence | None = None
    provenance: tuple[str, ...] = ()
    source_quality_selected: bool = True
    user_asserted_permission: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _safe_ref("context candidate id", self.id))
        object.__setattr__(self, "scope_id", _safe_ref("scope_id", self.scope_id))
        object.__setattr__(self, "resource_ref", _safe_ref("resource_ref", self.resource_ref))
        if self.evidence is not None and not isinstance(self.evidence, Evidence):
            raise ContextPermissionError("evidence must be Evidence or None")
        if not isinstance(self.source_quality_selected, bool):
            raise ContextPermissionError("source_quality_selected must be boolean")
        if not isinstance(self.user_asserted_permission, bool):
            raise ContextPermissionError("user_asserted_permission must be boolean")
        if isinstance(self.provenance, (str, bytes)):
            raise ContextPermissionError("provenance must be a tuple of strings")
        provenance = tuple(_safe_ref("provenance", item) for item in self.provenance)
        if len(provenance) > MAX_PROVENANCE_ITEMS:
            raise ContextPermissionError("provenance exceeds bounded limit")
        object.__setattr__(self, "provenance", provenance)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "scope_id": self.scope_id,
            "resource_ref": self.resource_ref,
            "evidence_id": self.evidence.id if self.evidence is not None else None,
            "provenance": list(self.provenance),
            "source_quality_selected": self.source_quality_selected,
        }


@dataclass(frozen=True, slots=True)
class ContextEnvelope:
    """Product-neutral context offered for a single request/model turn."""

    app_id: str
    request_id: str
    candidates: tuple[ContextCandidate, ...]
    source_quality_gate_applied: bool
    policy_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_id", _safe_ref("app_id", self.app_id))
        object.__setattr__(self, "request_id", _safe_ref("request_id", self.request_id))
        if not isinstance(self.source_quality_gate_applied, bool):
            raise ContextPermissionError("source_quality_gate_applied must be boolean")
        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))
        if len(self.candidates) > MAX_CONTEXT_CANDIDATES:
            raise ContextPermissionError("candidates exceed bounded limit")
        if any(not isinstance(item, ContextCandidate) for item in self.candidates):
            raise ContextPermissionError("candidates must contain ContextCandidate values")
        object.__setattr__(self, "policy_hints", _safe_tuple("policy_hints", self.policy_hints))


@dataclass(frozen=True, slots=True)
class KnowledgeBoundary:
    """Trusted product-supplied permission boundary.

    Products may narrow the boundary by supplying fewer allowed scopes/resources
    or additional denied scopes/resources. Core rejects attempts to represent an
    unavailable trusted boundary as permissive context.
    """

    allowed_scope_ids: tuple[str, ...]
    allowed_resource_refs: tuple[str, ...] = ()
    denied_scope_ids: tuple[str, ...] = ()
    denied_resource_refs: tuple[str, ...] = ()
    boundary_available: bool = True
    require_trusted_boundary: bool = True
    max_allowed_context: int = 8
    policy_version: str = "context-permission:v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_scope_ids", _safe_tuple("allowed_scope_ids", self.allowed_scope_ids))
        object.__setattr__(self, "allowed_resource_refs", _safe_tuple("allowed_resource_refs", self.allowed_resource_refs))
        object.__setattr__(self, "denied_scope_ids", _safe_tuple("denied_scope_ids", self.denied_scope_ids))
        object.__setattr__(self, "denied_resource_refs", _safe_tuple("denied_resource_refs", self.denied_resource_refs))
        if set(self.allowed_scope_ids) & set(self.denied_scope_ids):
            raise ContextPermissionError("allowed and denied scopes overlap")
        if set(self.allowed_resource_refs) & set(self.denied_resource_refs):
            raise ContextPermissionError("allowed and denied resources overlap")
        if not isinstance(self.boundary_available, bool):
            raise ContextPermissionError("boundary_available must be boolean")
        if self.require_trusted_boundary is not True:
            raise ContextPermissionError("trusted boundary is mandatory and cannot be disabled")
        if (
            isinstance(self.max_allowed_context, bool)
            or not isinstance(self.max_allowed_context, int)
            or not 1 <= self.max_allowed_context <= MAX_ALLOWED_CONTEXT
        ):
            raise ContextPermissionError(f"max_allowed_context must be between 1 and {MAX_ALLOWED_CONTEXT}")
        object.__setattr__(self, "policy_version", _safe_ref("policy_version", self.policy_version))


@dataclass(frozen=True, slots=True)
class FilteredContext:
    candidate: ContextCandidate
    reason_codes: tuple[ContextFilterReason, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, ContextCandidate):
            raise ContextPermissionError("candidate must be ContextCandidate")
        if not isinstance(self.reason_codes, tuple) or not self.reason_codes:
            raise ContextPermissionError("reason_codes must be a non-empty tuple")
        if any(not isinstance(reason, ContextFilterReason) for reason in self.reason_codes):
            raise ContextPermissionError("reason_codes must contain ContextFilterReason values")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate.id,
            "evidence_id": self.candidate.evidence.id if self.candidate.evidence is not None else None,
            "scope_id": self.candidate.scope_id,
            "resource_ref": self.candidate.resource_ref,
            "filter_reason": [reason.value for reason in self.reason_codes],
            "provenance": list(self.candidate.provenance),
        }


@dataclass(frozen=True, slots=True)
class ContextPermissionProjection:
    allowed_context: tuple[ContextCandidate, ...]
    filtered_context: tuple[FilteredContext, ...]
    disposition: BoundaryDisposition
    policy_version: str
    source_quality_gate_applied: bool

    def __post_init__(self) -> None:
        if any(not isinstance(item, ContextCandidate) for item in self.allowed_context):
            raise ContextPermissionError("allowed_context must contain ContextCandidate values")
        if any(not isinstance(item, FilteredContext) for item in self.filtered_context):
            raise ContextPermissionError("filtered_context must contain FilteredContext values")
        if not isinstance(self.disposition, BoundaryDisposition):
            raise ContextPermissionError("disposition must be BoundaryDisposition")
        object.__setattr__(self, "policy_version", _safe_ref("policy_version", self.policy_version))
        if not isinstance(self.source_quality_gate_applied, bool):
            raise ContextPermissionError("source_quality_gate_applied must be boolean")

    def diagnostics(self) -> dict[str, object]:
        reasons = sorted({reason.value for item in self.filtered_context for reason in item.reason_codes})
        return {
            "context_candidate_count": len(self.allowed_context) + len(self.filtered_context),
            "context_allowed_count": len(self.allowed_context),
            "context_filtered_count": len(self.filtered_context),
            "boundary_disposition": self.disposition.value,
            "filter_reason_codes": reasons,
            "policy_version": self.policy_version,
            "source_quality_gate_applied": self.source_quality_gate_applied,
        }

    def to_public_dict(self) -> dict[str, object]:
        return {
            "allowed_context": [item.to_public_dict() for item in self.allowed_context],
            "filtered_context": [item.to_public_dict() for item in self.filtered_context],
            "diagnostics": self.diagnostics(),
        }


def candidate_from_evidence(
    evidence: Evidence,
    *,
    scope_id: str,
    resource_ref: str | None = None,
    source_quality_selected: bool = True,
) -> ContextCandidate:
    """Create a product-neutral context candidate from accepted evidence."""

    if not isinstance(evidence, Evidence):
        raise ContextPermissionError("evidence must be Evidence")
    resolved_resource = resource_ref or f"evidence/{evidence.id}"
    return ContextCandidate(
        id=f"ctx/{evidence.id}",
        scope_id=scope_id,
        resource_ref=resolved_resource,
        evidence=evidence,
        provenance=("source_quality",),
        source_quality_selected=source_quality_selected,
    )


def context_envelope_from_source_selection(
    *,
    app_id: str,
    request_id: str,
    selection: SourceQualitySelection,
    scope_id: str,
) -> ContextEnvelope:
    """Compose after #1308 without re-ranking or resurrecting rejected evidence."""

    if not isinstance(selection, SourceQualitySelection):
        raise ContextPermissionError("selection must be SourceQualitySelection")
    return ContextEnvelope(
        app_id=app_id,
        request_id=request_id,
        candidates=tuple(candidate_from_evidence(item, scope_id=scope_id) for item in selection.evidence),
        source_quality_gate_applied=True,
        policy_hints=("source_quality_selection_accepted",),
    )


def narrow_knowledge_boundary(
    boundary: KnowledgeBoundary,
    *,
    allowed_scope_ids: Sequence[str] | None = None,
    allowed_resource_refs: Sequence[str] | None = None,
    denied_scope_ids: Sequence[str] = (),
    denied_resource_refs: Sequence[str] = (),
    max_allowed_context: int | None = None,
) -> KnowledgeBoundary:
    """Return a narrower trusted boundary for a product adapter."""

    if not isinstance(boundary, KnowledgeBoundary):
        raise ContextPermissionError("boundary must be KnowledgeBoundary")
    if allowed_scope_ids is None:
        narrowed_scopes = boundary.allowed_scope_ids
    else:
        requested = set(_safe_tuple("allowed_scope_ids", allowed_scope_ids))
        narrowed_scopes = tuple(scope for scope in boundary.allowed_scope_ids if scope in requested)
    if allowed_resource_refs is None:
        narrowed_resources = boundary.allowed_resource_refs
    else:
        requested_resources = set(_safe_tuple("allowed_resource_refs", allowed_resource_refs))
        narrowed_resources = tuple(ref for ref in boundary.allowed_resource_refs if ref in requested_resources)
    resolved_max = boundary.max_allowed_context if max_allowed_context is None else min(boundary.max_allowed_context, max_allowed_context)
    return KnowledgeBoundary(
        allowed_scope_ids=narrowed_scopes,
        allowed_resource_refs=narrowed_resources,
        denied_scope_ids=tuple(dict.fromkeys(boundary.denied_scope_ids + _safe_tuple("denied_scope_ids", denied_scope_ids))),
        denied_resource_refs=tuple(
            dict.fromkeys(boundary.denied_resource_refs + _safe_tuple("denied_resource_refs", denied_resource_refs))
        ),
        boundary_available=boundary.boundary_available,
        require_trusted_boundary=True,
        max_allowed_context=resolved_max,
        policy_version=boundary.policy_version,
    )


def _resource_allowed(candidate: ContextCandidate, boundary: KnowledgeBoundary) -> bool:
    if not boundary.allowed_resource_refs:
        return True
    return candidate.resource_ref in boundary.allowed_resource_refs


def _scope_allowed(candidate: ContextCandidate, boundary: KnowledgeBoundary) -> bool:
    return candidate.scope_id in boundary.allowed_scope_ids


def _filter_reasons(candidate: ContextCandidate, boundary: KnowledgeBoundary) -> tuple[ContextFilterReason, ...]:
    reasons: list[ContextFilterReason] = []
    if candidate.user_asserted_permission:
        reasons.append(ContextFilterReason.USER_SELF_ASSERTED_PERMISSION)
    if not candidate.source_quality_selected:
        reasons.append(ContextFilterReason.SOURCE_QUALITY_NOT_SELECTED)
    if candidate.scope_id in boundary.denied_scope_ids:
        reasons.append(ContextFilterReason.DENIED_SCOPE)
    if candidate.resource_ref in boundary.denied_resource_refs:
        reasons.append(ContextFilterReason.DENIED_RESOURCE)
    if not _scope_allowed(candidate, boundary):
        reasons.append(ContextFilterReason.OUTSIDE_ALLOWED_SCOPE)
    if not _resource_allowed(candidate, boundary):
        reasons.append(ContextFilterReason.OUTSIDE_ALLOWED_RESOURCE)
    return tuple(reasons)


def project_context_permission(
    envelope: ContextEnvelope,
    boundary: KnowledgeBoundary,
) -> ContextPermissionProjection:
    """Filter context before model invocation.

    The model receives only `allowed_context`; `filtered_context` is diagnostic
    metadata and must not be assembled into the prompt.
    """

    if not isinstance(envelope, ContextEnvelope):
        raise ContextPermissionError("envelope must be ContextEnvelope")
    if not isinstance(boundary, KnowledgeBoundary):
        raise ContextPermissionError("boundary must be KnowledgeBoundary")

    if not boundary.boundary_available:
        filtered = tuple(
            FilteredContext(item, (ContextFilterReason.BOUNDARY_UNAVAILABLE,)) for item in envelope.candidates
        )
        return ContextPermissionProjection(
            allowed_context=(),
            filtered_context=filtered,
            disposition=BoundaryDisposition.BOUNDARY_UNAVAILABLE,
            policy_version=boundary.policy_version,
            source_quality_gate_applied=envelope.source_quality_gate_applied,
        )

    allowed: list[ContextCandidate] = []
    filtered_items: list[FilteredContext] = []
    for candidate in envelope.candidates:
        reasons = _filter_reasons(candidate, boundary)
        if reasons:
            filtered_items.append(FilteredContext(candidate, reasons))
            continue
        if len(allowed) >= boundary.max_allowed_context:
            filtered_items.append(FilteredContext(candidate, (ContextFilterReason.CONTEXT_LIMIT_EXCEEDED,)))
            continue
        allowed.append(candidate)

    if allowed:
        disposition = BoundaryDisposition.PERMITTED
    elif envelope.candidates:
        disposition = BoundaryDisposition.OUTSIDE_KNOWLEDGE_BOUNDARY
    else:
        disposition = BoundaryDisposition.INSUFFICIENT_ALLOWED_CONTEXT

    return ContextPermissionProjection(
        allowed_context=tuple(allowed),
        filtered_context=tuple(filtered_items),
        disposition=disposition,
        policy_version=boundary.policy_version,
        source_quality_gate_applied=envelope.source_quality_gate_applied,
    )
