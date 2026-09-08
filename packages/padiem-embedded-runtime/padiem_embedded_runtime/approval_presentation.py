"""Public-safe approval/action-confirmation presentation for IP-SIDECAR (S6).

Approval proposals, confirmation intents, decision states, and upstream
references arrive from untrusted host surfaces. This module projects them
into bounded, deterministic, display-only views. It never verifies
decisions, never mints approval authority or tokens, never executes
actions, never calls Engine/provider/browser network/host backend, and
never carries raw Tool args/results, terminal output, diffs, credentials,
or hidden reasoning: approval requirement evaluation, decision
verification, expiry/scope enforcement, and authority/evidence issuance
belong to Core/Engine/P01; product-domain meaning and delivery policy
belong to product adapters.

Pipeline:

    untrusted approval/intent/state/reference input
      -> bounded allowlisted normalization
      -> display-only projection (no execution side effects)
      -> host-safe empty/degraded/unavailable/rejected states
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .errors import SidecarContractError

STATUS_READY = "ready"
STATUS_EMPTY = "empty"
STATUS_DEGRADED = "degraded"
PRESENTATION_STATUSES = frozenset({STATUS_READY, STATUS_EMPTY, STATUS_DEGRADED})

STATUS_STAGED = "staged"
STATUS_PRESENTED = "presented"
STATUS_REJECTED = "rejected"

DROP_REASON_MALFORMED_ITEM = "MALFORMED_ITEM"
DROP_REASON_INVALID_FIELD = "INVALID_FIELD"
_DROP_REASONS = frozenset({DROP_REASON_MALFORMED_ITEM, DROP_REASON_INVALID_FIELD})

INTENT_REASONS = frozenset(
    {"MALFORMED_INPUT", "UNKNOWN_FIELDS", "INVALID_INTENT", "INVALID_PROPOSAL_ID"}
)
REFERENCE_REASONS = frozenset(
    {"MALFORMED_ITEM", "URL_SHAPED_REFERENCE", "INVALID_REFERENCE"}
)

ALLOWED_PROPOSAL_FIELDS = frozenset({"proposal_id", "tool_id", "requirement", "summary"})

MAX_PROPOSALS = 8
MAX_IDENTIFIER_CHARS = 128
MAX_REQUIREMENT_CHARS = 64
MAX_SUMMARY_CHARS = 120

CONFIRMATION_INTENTS = frozenset({"approve", "reject", "confirm", "cancel"})
ALLOWED_INTENT_FIELDS = frozenset({"intent", "proposal_id"})

APPROVAL_STATES = frozenset(
    {"pending", "approved", "rejected", "expired", "unavailable"}
)
STATE_REASON_CODES = frozenset(
    {"USER_REJECTED", "AUTHORITY_TIMEOUT", "AUTHORITY_UNAVAILABLE", "INVALID_HOST_INPUT"}
)
ALLOWED_STATE_FIELDS = frozenset({"state", "reason_code"})

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_URL_SHAPE_RE = re.compile(r"://")
_GUARDED_VALUE_RE = re.compile(
    r"secret|passwd|password|credential|api[_-]?key|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|bearer|authorization|"
    r"reasoning|chain[_-]of[_-]thought|tool[_-]?arg|stdout|stderr|traceback|"
    r"diff --git|unified diff|<\s*/?\s*[a-z]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ApprovalProposal:
    """One normalized, bounded, display-only approval proposal summary."""

    proposal_id: str
    tool_id: str
    requirement: str
    summary: str = ""

    def to_public_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "tool_id": self.tool_id,
            "requirement": self.requirement,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class PresentedProposal:
    """A proposal with its deterministic presentation label."""

    label: str
    proposal: ApprovalProposal

    def to_public_dict(self) -> dict[str, object]:
        return {"label": self.label, **self.proposal.to_public_dict()}


@dataclass(frozen=True)
class ProposalPresentation:
    """Immutable host-safe proposal view. Never carries raw input."""

    status: str
    proposals: tuple[PresentedProposal, ...] = field(default_factory=tuple)
    dropped_count: int = 0
    drop_reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in PRESENTATION_STATUSES:
            raise SidecarContractError("presentation status is not an allowlisted code")
        for reason in self.drop_reasons:
            if reason not in _DROP_REASONS:
                raise SidecarContractError("drop reason is not an allowlisted code")
        if self.dropped_count < 0:
            raise SidecarContractError("dropped_count must be >= 0")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "proposals": [p.to_public_dict() for p in self.proposals],
            "dropped_count": self.dropped_count,
            "drop_reasons": list(self.drop_reasons),
        }


@dataclass(frozen=True)
class ConfirmationIntentPresentation:
    """Display-only staged intent. Staging never executes or transports."""

    status: str
    intent: str = ""
    proposal_id: str = ""
    reason_code: str = ""

    def __post_init__(self) -> None:
        if self.status not in (STATUS_STAGED, STATUS_REJECTED):
            raise SidecarContractError("intent status is not an allowlisted code")
        if self.status == STATUS_STAGED:
            if self.intent not in CONFIRMATION_INTENTS:
                raise SidecarContractError("staged intent must be an allowlisted intent")
            if _IDENTIFIER_RE.fullmatch(self.proposal_id) is None:
                raise SidecarContractError("staged proposal_id must be a bounded identifier")
            if self.reason_code:
                raise SidecarContractError("staged intents carry no reason code")
        else:
            if self.intent or self.proposal_id:
                raise SidecarContractError("rejected intents never echo values")
            if self.reason_code not in INTENT_REASONS:
                raise SidecarContractError("intent reason is not an allowlisted code")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "intent": self.intent,
            "proposal_id": self.proposal_id,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class ApprovalStatePresentation:
    """Host/upstream-driven display state; malformed input degrades safely."""

    state: str
    reason_code: str = ""
    degraded: bool = False

    def __post_init__(self) -> None:
        if self.state not in APPROVAL_STATES:
            raise SidecarContractError("approval state is not an allowlisted state")
        if self.reason_code and self.reason_code not in STATE_REASON_CODES:
            raise SidecarContractError("state reason is not an allowlisted code")

    def to_public_dict(self) -> dict[str, object]:
        return {"state": self.state, "reason_code": self.reason_code, "degraded": self.degraded}


@dataclass(frozen=True)
class PublicReferenceDisplay:
    """Opaque display token for upstream-issued refs; never executable."""

    status: str
    label: str = ""
    reason_code: str = ""

    def __post_init__(self) -> None:
        if self.status not in (STATUS_PRESENTED, STATUS_REJECTED):
            raise SidecarContractError("reference status is not an allowlisted code")
        if self.status == STATUS_PRESENTED:
            if _IDENTIFIER_RE.fullmatch(self.label) is None:
                raise SidecarContractError("presented reference must be a bounded identifier")
            if self.reason_code:
                raise SidecarContractError("presented references carry no reason code")
        else:
            if self.label:
                raise SidecarContractError("rejected references never retain the raw value")
            if self.reason_code not in REFERENCE_REASONS:
                raise SidecarContractError("reference reason is not an allowlisted code")

    def to_public_dict(self) -> dict[str, object]:
        return {"status": self.status, "label": self.label, "reason_code": self.reason_code}


def _check_identifier(value: object, limit: int, field_name: str) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise SidecarContractError(f"proposal {field_name} must be bounded text")
    if _IDENTIFIER_RE.fullmatch(value) is None or _GUARDED_VALUE_RE.search(value):
        raise SidecarContractError(f"proposal {field_name} must be a bounded public identifier")
    return value


def normalize_approval_proposal(raw: Mapping[str, object]) -> ApprovalProposal:
    """Validate one untrusted proposal into a display-only view or fail closed.

    Only ``proposal_id``/``tool_id``/``requirement``/``summary`` are accepted.
    Markup/URL/path/secret/tool/terminal/diff-shaped values are rejected; raw
    Tool args/results can never pass.
    """
    if not isinstance(raw, Mapping):
        raise SidecarContractError("proposal must be a mapping")
    unknown = sorted(k for k in raw if k not in ALLOWED_PROPOSAL_FIELDS)
    if unknown:
        raise SidecarContractError(f"unknown proposal fields: {', '.join(unknown)}")
    if "proposal_id" not in raw or "tool_id" not in raw or "requirement" not in raw:
        raise SidecarContractError("proposal requires proposal_id, tool_id, and requirement")

    proposal_id = _check_identifier(raw["proposal_id"], MAX_IDENTIFIER_CHARS, "proposal_id")
    tool_id = _check_identifier(raw["tool_id"], MAX_IDENTIFIER_CHARS, "tool_id")
    requirement = _check_identifier(raw["requirement"], MAX_REQUIREMENT_CHARS, "requirement")

    summary = raw.get("summary", "")
    if not isinstance(summary, str) or len(summary) > MAX_SUMMARY_CHARS:
        raise SidecarContractError("proposal summary must be bounded text")
    if _GUARDED_VALUE_RE.search(summary) or _URL_SHAPE_RE.search(summary):
        raise SidecarContractError("proposal summary resembles non-public material")

    return ApprovalProposal(
        proposal_id=proposal_id, tool_id=tool_id, requirement=requirement, summary=summary
    )


def present_approval_proposals(raw_items: Sequence[object]) -> ProposalPresentation:
    """Project untrusted proposal input into a deterministic host-safe view.

    Malformed items are dropped (counted, reason-coded, values never
    retained). Surviving items keep input order, are deduplicated on
    ``proposal_id``, are capped at ``MAX_PROPOSALS``, and receive ``[1]..[n]``
    labels. This function never raises for untrusted data.
    """
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        return ProposalPresentation(
            status=STATUS_DEGRADED,
            drop_reasons=(DROP_REASON_MALFORMED_ITEM,),
            dropped_count=1,
        )

    normalized: list[ApprovalProposal] = []
    drop_reasons: set[str] = set()
    dropped = 0
    for raw in raw_items:
        if len(normalized) >= MAX_PROPOSALS:
            dropped += 1
            drop_reasons.add(DROP_REASON_MALFORMED_ITEM)
            continue
        try:
            normalized.append(normalize_approval_proposal(raw))
        except SidecarContractError:
            dropped += 1
            drop_reasons.add(
                DROP_REASON_INVALID_FIELD
                if isinstance(raw, Mapping)
                else DROP_REASON_MALFORMED_ITEM
            )

    seen: dict[str, ApprovalProposal] = {}
    for proposal in normalized:
        if proposal.proposal_id not in seen:
            seen[proposal.proposal_id] = proposal

    presented = tuple(
        PresentedProposal(label=f"[{position}]", proposal=proposal)
        for position, proposal in enumerate(seen.values(), start=1)
    )

    if dropped:
        status = STATUS_DEGRADED
    elif not presented:
        status = STATUS_EMPTY
    else:
        status = STATUS_READY
    return ProposalPresentation(
        status=status,
        proposals=presented,
        dropped_count=dropped,
        drop_reasons=tuple(sorted(drop_reasons)),
    )


def present_confirmation_intent(raw: Mapping[str, object]) -> ConfirmationIntentPresentation:
    """Stage one allowlisted confirmation intent for host handoff.

    Staging is a display-only presentation state: nothing is executed, no
    Engine/provider/host-backend call happens, and no approval authority or
    token is minted. Invalid input is rejected with an allowlisted reason
    code and never echoes the raw value. This function never raises.
    """
    if not isinstance(raw, Mapping):
        return ConfirmationIntentPresentation(
            status=STATUS_REJECTED, reason_code="MALFORMED_INPUT"
        )
    if any(k not in ALLOWED_INTENT_FIELDS for k in raw):
        return ConfirmationIntentPresentation(
            status=STATUS_REJECTED, reason_code="UNKNOWN_FIELDS"
        )
    intent = raw.get("intent")
    if not isinstance(intent, str) or intent not in CONFIRMATION_INTENTS:
        return ConfirmationIntentPresentation(
            status=STATUS_REJECTED, reason_code="INVALID_INTENT"
        )
    proposal_id = raw.get("proposal_id")
    if (
        not isinstance(proposal_id, str)
        or len(proposal_id) > MAX_IDENTIFIER_CHARS
        or _IDENTIFIER_RE.fullmatch(proposal_id) is None
    ):
        return ConfirmationIntentPresentation(
            status=STATUS_REJECTED, reason_code="INVALID_PROPOSAL_ID"
        )
    return ConfirmationIntentPresentation(
        status=STATUS_STAGED, intent=intent, proposal_id=proposal_id
    )


def present_approval_state(raw: Mapping[str, object]) -> ApprovalStatePresentation:
    """Project host/upstream-driven approval state into a safe display view.

    Only allowlisted states and reason codes pass. The sidecar never decides
    expiry or verification itself; malformed input degrades to
    ``unavailable``/``INVALID_HOST_INPUT`` instead of raising.
    """
    fallback = ApprovalStatePresentation(
        state="unavailable", reason_code="INVALID_HOST_INPUT", degraded=True
    )
    if not isinstance(raw, Mapping):
        return fallback
    if any(k not in ALLOWED_STATE_FIELDS for k in raw):
        return fallback
    state = raw.get("state")
    if not isinstance(state, str) or state not in APPROVAL_STATES:
        return fallback
    reason_raw = raw.get("reason_code", "")
    if not isinstance(reason_raw, str) or (
        reason_raw and reason_raw not in STATE_REASON_CODES
    ):
        return fallback
    if reason_raw and state not in ("rejected", "expired", "unavailable"):
        return fallback
    return ApprovalStatePresentation(state=state, reason_code=reason_raw, degraded=False)


def present_public_reference(raw_ref: object) -> PublicReferenceDisplay:
    """Project one upstream-issued public reference into an opaque display token.

    Only bounded identifier-shaped values are presented. URL-, path-, or
    markup-shaped values are rejected without retaining the raw value; the
    token is never interpreted as an executable URL, credential, token, or
    approval authority, and the sidecar never mints references.
    """
    if not isinstance(raw_ref, str):
        return PublicReferenceDisplay(status=STATUS_REJECTED, reason_code="MALFORMED_ITEM")
    if _URL_SHAPE_RE.search(raw_ref) or raw_ref.lower().startswith(("http:", "https:", "data:")):
        return PublicReferenceDisplay(
            status=STATUS_REJECTED, reason_code="URL_SHAPED_REFERENCE"
        )
    if len(raw_ref) > MAX_IDENTIFIER_CHARS or _IDENTIFIER_RE.fullmatch(raw_ref) is None:
        return PublicReferenceDisplay(
            status=STATUS_REJECTED, reason_code="INVALID_REFERENCE"
        )
    return PublicReferenceDisplay(status=STATUS_PRESENTED, label=raw_ref)
