"""#3611 — `browser.open` open-only contract (trusted work ticket -> P01 -> trusted host).

Scope of this module is deliberately narrow: it authorizes and correlates a **single
URL open**. It never exposes browser control.

Authority boundary (no new authority is created here):

* capability evaluation reuses ``local_agent_permissions.evaluate_local_permission``
  (`browser.open` stays the existing global `ASK` capability);
* the approval is the canonical P01 shape from ``padiem_ai_core.agent_approval``
  (an ``ApprovalPause`` whose ``tool_id`` is `browser.open`, plus a
  ``VerifiedApprovalDecision``); nothing here mints or verifies a decision;
* the grant is one-shot with the same consumption semantics as the Windows
  execution lane, and is bounded by the reviewed grant family TTL limits;
* the URL policy is the canonical public-URL contract
  (``padiem_ai_core.web_runtime.normalize_public_url``) — this module does not
  re-implement or weaken it.

Page-derived bytes are zero: the receipt schema is pinned to an exact field set
and any page-content field (title/body/HTML/DOM/screenshot/PDF/...) is refused by
construction.

    BROWSER_OPEN_IMPLEMENTED = True
    BROWSER_CONTROL_IMPLEMENTED = False
    BROWSER_OPEN_PAGE_DERIVED_BYTES = 0
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Protocol

from padiem_ai_core.agent_approval import ApprovalOutcome, ApprovalPause, VerifiedApprovalDecision
from padiem_ai_core.web_runtime import normalize_public_url

from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile
from .local_agent_permissions import (
    LocalCapability,
    LocalEnforcementResult,
    LocalPermissionRequest,
    DevicePermissionProfile,
    evaluate_local_permission,
)


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

BROWSER_OPEN_TOOL_ID = "browser.open"
BROWSER_OPEN_HOST_REF = "desktop-trusted-main-ephemeral-view@1"
DEFAULT_BROWSER_OPEN_TTL_SECONDS = 300
MAX_BROWSER_OPEN_TTL_SECONDS = 900
MAX_BROWSER_OPEN_REDIRECTS = 5

# Page-derived content that may never appear on this surface, in a request, a
# grant or a receipt. The receipt field-set assertion below is the enforcement.
_FORBIDDEN_PAGE_DERIVED_FIELDS = frozenset(
    {
        "title",
        "page_title",
        "text",
        "body",
        "body_text",
        "html",
        "page_source",
        "dom",
        "snapshot",
        "screenshot",
        "image",
        "pdf",
        "dialog_text",
        "form_values",
        "attributes",
        "cookies",
        "local_storage",
        "session_storage",
    }
)

# The receipt schema is pinned in two parts: the fields the dataclass declares, and
# the fail-closed projection flags ``safe_dict`` adds. Their union is the complete
# external receipt schema (22 fields), none of them page-derived.
BROWSER_OPEN_RECEIPT_DECLARED_FIELDS = frozenset(
    {
        "open_id",
        "run_id",
        "device_id",
        "host_lease_ref",
        "requested_url_normalized",
        "final_url_normalized",
        "load_outcome",
        "redirect_count",
        "dialogs_suppressed",
        "opened_at",
        "closed_at",
        "elapsed_ms",
        "host_ref",
        "request_fingerprint",
        "p01_approval_ref",
        "admission_ref",
        "revision_ref",
    }
)

BROWSER_OPEN_RECEIPT_PROJECTED_FIELDS = frozenset(
    {
        "page_content_included",
        "cookie_included",
        "credential_included",
        "dom_api_exposed",
        "network_scope",
    }
)

BROWSER_OPEN_RECEIPT_FIELDS = (
    BROWSER_OPEN_RECEIPT_DECLARED_FIELDS | BROWSER_OPEN_RECEIPT_PROJECTED_FIELDS
)


class BrowserOpenRefusal(ContractError):
    """Fail-closed refusal carrying a stable, user-projectable code."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class BrowserOpenOutcome(str, Enum):
    LOADED = "loaded"
    NAVIGATION_BLOCKED = "navigation_blocked"
    LOAD_FAILED = "load_failed"
    POLICY_DENIED = "policy_denied"
    HOST_UNAVAILABLE = "host_unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class BrowserOpenRequest:
    """One approved URL open. The capability is fixed, never a parameter."""

    open_id: str
    run_id: str
    device_id: str
    ticket_ref: str
    target_url: str
    requested_at: datetime
    ttl_seconds: int = DEFAULT_BROWSER_OPEN_TTL_SECONDS
    # Derived field: always the canonical policy value, never caller-supplied.
    normalized_url: str = ""

    def __post_init__(self) -> None:
        for field_name in ("open_id", "run_id", "device_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        object.__setattr__(self, "ticket_ref", _ref(self.ticket_ref, "ticket_ref"))
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, int)
            or not 60 <= self.ttl_seconds <= MAX_BROWSER_OPEN_TTL_SECONDS
        ):
            raise ContractError(
                f"ttl_seconds must be between 60 and {MAX_BROWSER_OPEN_TTL_SECONDS}"
            )
        if not isinstance(self.target_url, str):
            raise ContractError("target_url must be a string")
        try:
            normalized = normalize_public_url(self.target_url)
        except ValueError as exc:
            raise BrowserOpenRefusal(
                "policy_denied", "browser open target URL is not a permitted public URL"
            ) from exc
        object.__setattr__(self, "target_url", self.target_url.strip())
        object.__setattr__(self, "normalized_url", normalized)

    @property
    def capability(self) -> LocalCapability:
        return LocalCapability.BROWSER_OPEN

    def safe_dict(self) -> dict[str, Any]:
        return {
            "open_id": self.open_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "ticket_ref": self.ticket_ref,
            "capability": self.capability.value,
            "normalized_url": self.normalized_url,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "ttl_seconds": self.ttl_seconds,
            "page_derived_bytes": 0,
            "cookie_material": False,
            "credential_material": False,
        }


def browser_open_fingerprint(request: BrowserOpenRequest) -> str:
    """Exact immutable binding for the approval pause and the one-shot grant."""

    if not isinstance(request, BrowserOpenRequest):
        raise ContractError("request must be BrowserOpenRequest")
    payload = {
        "capability": request.capability.value,
        "open_id": request.open_id,
        "run_id": request.run_id,
        "device_id": request.device_id,
        "ticket_ref": request.ticket_ref,
        "normalized_url": request.normalized_url,
        "ttl_seconds": request.ttl_seconds,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def browser_open_target_ref(request: BrowserOpenRequest) -> str:
    """Bounded, URL-free reference for the local permission record.

    ``LocalPermissionRequest.target_ref`` is a bounded safe reference and cannot
    carry a full URL (query strings and percent-escapes are outside that grammar).
    The digest binds the exact normalized URL without copying it — or its query
    parameters — into the local-policy record.
    """

    if not isinstance(request, BrowserOpenRequest):
        raise ContractError("request must be BrowserOpenRequest")
    digest = hashlib.sha256(request.normalized_url.encode("utf-8")).hexdigest()
    return f"url_sha256_{digest}"


def browser_open_host_lease_ref(request: BrowserOpenRequest) -> str:
    """Deterministic, bounded lease reference for one approved open.

    The trusted main host owns the ephemeral view for exactly this lease, so the
    lease must be derivable from the *approved* request rather than supplied by a
    caller. Being a pure function of the request it can never address another
    run's view, and it carries no URL material.
    """

    if not isinstance(request, BrowserOpenRequest):
        raise ContractError("request must be BrowserOpenRequest")
    digest = hashlib.sha256(
        f"{request.open_id}:{request.run_id}:{request.device_id}".encode("utf-8")
    ).hexdigest()[:24]
    return f"browser_open_lease_{digest}"


@dataclass(frozen=True, slots=True)
class TrustedBrowserOpenGrant:
    grant_id: str
    open_id: str
    run_id: str
    device_id: str
    ticket_ref: str
    normalized_url: str
    request_fingerprint: str
    pause_id: str
    p01_approval_ref: str
    evidence_ref: str
    host_lease_ref: str
    local_policy_ref: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("grant_id", "open_id", "run_id", "device_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        for field_name in (
            "ticket_ref",
            "request_fingerprint",
            "pause_id",
            "p01_approval_ref",
            "evidence_ref",
            "host_lease_ref",
            "local_policy_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.normalized_url, str) or not self.normalized_url:
            raise ContractError("grant normalized_url is required")
        try:
            canonical = normalize_public_url(self.normalized_url)
        except ValueError as exc:
            raise ContractError("grant normalized_url is not a permitted public URL") from exc
        if canonical != self.normalized_url:
            raise ContractError("grant normalized_url must be the canonical policy value")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        lifetime = (expires - issued).total_seconds()
        if not 0 < lifetime <= MAX_BROWSER_OPEN_TTL_SECONDS:
            raise ContractError(
                f"browser open grant lifetime must be positive and at most "
                f"{MAX_BROWSER_OPEN_TTL_SECONDS} seconds"
            )
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def bound_request(self, request: BrowserOpenRequest) -> bool:
        return (
            request.open_id == self.open_id
            and request.run_id == self.run_id
            and request.device_id == self.device_id
            and request.ticket_ref == self.ticket_ref
            and request.normalized_url == self.normalized_url
            and browser_open_fingerprint(request) == self.request_fingerprint
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "open_id": self.open_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "ticket_ref": self.ticket_ref,
            "normalized_url": self.normalized_url,
            "request_fingerprint": self.request_fingerprint,
            "pause_id": self.pause_id,
            "p01_approval_ref": self.p01_approval_ref,
            "evidence_ref": self.evidence_ref,
            "host_lease_ref": self.host_lease_ref,
            "local_policy_ref": self.local_policy_ref,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "one_shot": True,
            "browser_control": False,
            "page_derived_bytes": 0,
        }


def authorize_browser_open(
    *,
    request: BrowserOpenRequest,
    profile: DevicePermissionProfile,
    device: LocalAgentDeviceProfile,
    pause: ApprovalPause,
    decision: VerifiedApprovalDecision,
    now: datetime,
    host_lease_ref: str,
) -> TrustedBrowserOpenGrant:
    """Compose an existing P01 approval into a one-shot browser-open grant.

    Fails closed on: local policy DENY, non-APPROVED decision, pause/tool/run
    mismatch, fingerprint mismatch (the request changed after approval), expired
    pause, or device mismatch. It cannot widen policy and creates no authority.
    """

    if not isinstance(request, BrowserOpenRequest):
        raise ContractError("request must be BrowserOpenRequest")
    if not isinstance(profile, DevicePermissionProfile):
        raise ContractError("profile must be DevicePermissionProfile")
    if not isinstance(device, LocalAgentDeviceProfile):
        raise ContractError("device must be LocalAgentDeviceProfile")
    if not isinstance(pause, ApprovalPause):
        raise ContractError("pause must be canonical ApprovalPause")
    if not isinstance(decision, VerifiedApprovalDecision):
        raise ContractError("decision must be canonical VerifiedApprovalDecision")
    now = _aware(now, "now")
    host_lease_ref = _ref(host_lease_ref, "host_lease_ref")

    if profile.device_id != request.device_id or device.device_id != request.device_id:
        raise ContractError("browser open device mismatch")
    if decision.outcome is not ApprovalOutcome.APPROVED:
        raise BrowserOpenRefusal("grant_rejected", "canonical P01 decision is not approved")
    if decision.pause_id != pause.pause_id:
        raise ContractError("approval decision does not belong to this pause")
    if pause.tool_id != BROWSER_OPEN_TOOL_ID:
        raise ContractError("approval pause is not a browser.open pause")
    if pause.run_id != request.run_id:
        raise ContractError("approval pause run does not match the browser open run")
    if pause.invocation_sha256 != browser_open_fingerprint(request):
        raise BrowserOpenRefusal(
            "grant_rejected", "approval does not bind this exact browser open request"
        )
    if now >= pause.expires_at:
        raise BrowserOpenRefusal("grant_rejected", "approval pause has expired")

    permission_request = LocalPermissionRequest(
        action_id=f"browser_open_{request.open_id}",
        run_id=request.run_id,
        device_id=request.device_id,
        capability=request.capability,
        target_ref=browser_open_target_ref(request),
    )
    local_decision = evaluate_local_permission(profile=profile, request=permission_request)
    if local_decision.result is LocalEnforcementResult.DENIED:
        raise BrowserOpenRefusal("policy_denied", "local policy denied browser.open")
    if local_decision.capability is not request.capability:
        raise ContractError("recomputed local permission capability mismatch")

    expires_at = min(
        pause.expires_at,
        now + timedelta(seconds=request.ttl_seconds),
    )
    if expires_at <= now:
        raise BrowserOpenRefusal("grant_rejected", "browser open grant would already be expired")

    digest = hashlib.sha256(
        f"{request.open_id}:{decision.decision_id}:{host_lease_ref}".encode("utf-8")
    ).hexdigest()[:24]
    return TrustedBrowserOpenGrant(
        grant_id=f"browser_open_grant_{digest}",
        open_id=request.open_id,
        run_id=request.run_id,
        device_id=request.device_id,
        ticket_ref=request.ticket_ref,
        normalized_url=request.normalized_url,
        request_fingerprint=browser_open_fingerprint(request),
        pause_id=pause.pause_id,
        p01_approval_ref=decision.decision_id,
        evidence_ref=decision.evidence_ref,
        host_lease_ref=host_lease_ref,
        local_policy_ref=f"local:{local_decision.result.value}",
        issued_at=now,
        expires_at=expires_at,
    )


@dataclass(frozen=True, slots=True)
class BrowserOpenReceipt:
    """Bounded receipt. The field set is pinned: no page-derived content exists."""

    open_id: str
    run_id: str
    device_id: str
    host_lease_ref: str
    requested_url_normalized: str
    load_outcome: BrowserOpenOutcome
    redirect_count: int
    dialogs_suppressed: int
    opened_at: datetime
    closed_at: datetime
    elapsed_ms: int
    host_ref: str
    request_fingerprint: str
    p01_approval_ref: str
    admission_ref: str
    revision_ref: str
    final_url_normalized: str | None = None

    def __post_init__(self) -> None:
        present = {field.name for field in fields(type(self))}
        leaked = sorted(present & _FORBIDDEN_PAGE_DERIVED_FIELDS)
        if leaked:
            raise ContractError(
                f"browser open receipt must not carry page-derived fields: {', '.join(leaked)}"
            )
        if present != BROWSER_OPEN_RECEIPT_DECLARED_FIELDS:
            unexpected = sorted(present - BROWSER_OPEN_RECEIPT_DECLARED_FIELDS)
            missing = sorted(BROWSER_OPEN_RECEIPT_DECLARED_FIELDS - present)
            raise ContractError(
                "browser open receipt field set changed "
                f"(unexpected={unexpected}, missing={missing})"
            )
        if not isinstance(self.load_outcome, BrowserOpenOutcome):
            raise ContractError("load_outcome must be BrowserOpenOutcome")
        if (
            isinstance(self.redirect_count, bool)
            or not isinstance(self.redirect_count, int)
            or not 0 <= self.redirect_count <= MAX_BROWSER_OPEN_REDIRECTS
        ):
            raise ContractError(
                f"redirect_count must be between 0 and {MAX_BROWSER_OPEN_REDIRECTS}"
            )
        if (
            isinstance(self.dialogs_suppressed, bool)
            or not isinstance(self.dialogs_suppressed, int)
            or self.dialogs_suppressed < 0
        ):
            raise ContractError("dialogs_suppressed must be a non-negative integer")
        if isinstance(self.elapsed_ms, bool) or not isinstance(self.elapsed_ms, int) or self.elapsed_ms < 0:
            raise ContractError("elapsed_ms must be a non-negative integer")
        opened = _aware(self.opened_at, "opened_at")
        closed = _aware(self.closed_at, "closed_at")
        if closed < opened:
            raise ContractError("closed_at cannot precede opened_at")
        object.__setattr__(self, "opened_at", opened)
        object.__setattr__(self, "closed_at", closed)
        if self.final_url_normalized is not None:
            try:
                canonical = normalize_public_url(self.final_url_normalized)
            except ValueError as exc:
                raise ContractError("receipt final_url is not a permitted public URL") from exc
            if canonical != self.final_url_normalized:
                raise ContractError("receipt final_url must be the canonical policy value")

    def safe_dict(self) -> dict[str, Any]:
        projected = {
            "open_id": self.open_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "host_lease_ref": self.host_lease_ref,
            "requested_url_normalized": self.requested_url_normalized,
            "final_url_normalized": self.final_url_normalized,
            "load_outcome": self.load_outcome.value,
            "redirect_count": self.redirect_count,
            "dialogs_suppressed": self.dialogs_suppressed,
            "opened_at": self.opened_at.isoformat().replace("+00:00", "Z"),
            "closed_at": self.closed_at.isoformat().replace("+00:00", "Z"),
            "elapsed_ms": self.elapsed_ms,
            "host_ref": self.host_ref,
            "request_fingerprint": self.request_fingerprint,
            "p01_approval_ref": self.p01_approval_ref,
            "admission_ref": self.admission_ref,
            "revision_ref": self.revision_ref,
            "page_content_included": False,
            "cookie_included": False,
            "credential_included": False,
            "dom_api_exposed": False,
            "network_scope": "approved_url_fetch_only",
        }
        if set(projected) != BROWSER_OPEN_RECEIPT_FIELDS:
            raise ContractError("browser open receipt projection must equal the pinned schema")
        return projected


class BrowserOpenHostPort(Protocol):
    def open(
        self, *, request: BrowserOpenRequest, grant: TrustedBrowserOpenGrant, now: datetime
    ) -> BrowserOpenReceipt:
        ...


class UnconfiguredBrowserOpenHostPort:
    """Fails closed when no trusted host is wired — never a partial success."""

    def open(
        self, *, request: BrowserOpenRequest, grant: TrustedBrowserOpenGrant, now: datetime
    ) -> BrowserOpenReceipt:
        raise BrowserOpenRefusal("host_unavailable", "no trusted browser open host is configured")


class BrowserOpenGrantConsumer:
    """One-shot consumption of (request_fingerprint, p01_approval_ref)."""

    def __init__(self) -> None:
        self._consumed: set[tuple[str, str]] = set()

    def consume(
        self, *, request: BrowserOpenRequest, grant: TrustedBrowserOpenGrant, now: datetime
    ) -> None:
        if not grant.bound_request(request):
            raise BrowserOpenRefusal("grant_rejected", "grant does not bind this browser open request")
        now = _aware(now, "now")
        if now >= grant.expires_at:
            raise BrowserOpenRefusal("grant_rejected", "browser open grant has expired")
        key = (grant.request_fingerprint, grant.p01_approval_ref)
        if key in self._consumed:
            raise BrowserOpenRefusal("grant_rejected", "browser open grant has already been consumed")
        self._consumed.add(key)

    @property
    def consumed_count(self) -> int:
        return len(self._consumed)


def run_browser_open(
    *,
    request: BrowserOpenRequest,
    grant: TrustedBrowserOpenGrant,
    consumer: BrowserOpenGrantConsumer,
    host: BrowserOpenHostPort,
    now: datetime,
) -> BrowserOpenReceipt:
    """Consume the grant exactly once, then delegate to the trusted host."""

    if not isinstance(consumer, BrowserOpenGrantConsumer):
        raise ContractError("consumer must be BrowserOpenGrantConsumer")
    consumer.consume(request=request, grant=grant, now=now)
    receipt = host.open(request=request, grant=grant, now=now)
    if not isinstance(receipt, BrowserOpenReceipt):
        raise ContractError("browser open host did not return a BrowserOpenReceipt")
    if receipt.open_id != request.open_id or receipt.run_id != request.run_id:
        raise ContractError("browser open receipt correlation mismatch")
    if receipt.request_fingerprint != grant.request_fingerprint:
        raise ContractError("browser open receipt fingerprint mismatch")
    return receipt


BROWSER_OPEN_IMPLEMENTED = True
BROWSER_CONTROL_IMPLEMENTED = False
BROWSER_OPEN_PAGE_DERIVED_BYTES = 0
BROWSER_OPEN_USES_EXISTING_P01 = True
SECOND_APPROVAL_AUTHORITY = False
PERSISTENT_BROWSER_PROFILE_SUPPORTED = False
USER_BROWSER_PROFILE_REUSE_SUPPORTED = False
COOKIE_IMPORT_SUPPORTED = False
CREDENTIAL_IMPORT_SUPPORTED = False
