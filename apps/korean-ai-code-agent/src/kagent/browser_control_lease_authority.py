"""#3669 — canonical P01 + durable bounded-lease admission for `browser.control`.

CENTRAL ruling for #3669 (DECISION=B): this module is the trusted agent-side
admission authority. It reuses the canonical P01 approval machinery — the
existing `/v1/broker/p01-evidence` route, the existing `ApprovalPause` /
`VerifiedApprovalDecision` / `LocalPermissionRequest` objects and the local
policy recompute — and lands every admission in the **separate** canonical
`BrowserControlLeaseStore`. The `DurableRunStore` is not touched anywhere in
this path.

    NEW_APPROVAL_STORE=0
    NEW_DURABLE_LEASE_STORE=1
    DESKTOP_DURABLE_LEASE_AUTHORITY=NO
    DURABLE_RUN_STORE_TOUCHED=NO
    STEP_UP_EXECUTION=0
    LEASE_RENEWAL_SUPPORTED=NO
    AUTO_RECOVERY_REAUTHORIZE=NO
    REPLAY_CANDIDATES=0
    LEASE_ROW_GC=DEFERRED
    RENDERER_LEASE_MINTING=0

Issuance is lazy and idempotent: the first trusted `resolve` for a session
fingerprint fetches the canonical P01 evidence, validates it (decision
APPROVED, pause/decision correlation exact, capability `browser.control`,
exact request binding via the pause's invocation digest), recomputes the local
policy (a DENY wins even with an approved decision), and lands the lease row.
Every later resolve for the same fingerprint returns the existing row; a
fingerprint bound to different correlations fails closed.

The two-phase consumption contract (CENTRAL ruling §5) lives on the store:
PHASE A `resolve_lease` is read-only and never increments; PHASE B
`consume_action` is the one atomic durable slot write. This module only
delegates both, plus the explicit `revoke_lease` primitive.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from padiem_ai_core.agent_approval import (
    AgentApprovalError,
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    ContinuationStatus,
    VerifiedApprovalDecision,
    resolve_approval_pause,
)

from .browser_control_actions import (
    LEASE_ELIGIBLE_ACTIONS,
    LEASE_MAX_ACTIONS,
    LEASE_MAX_ACTIONS_HARD_CAP,
    LEASE_TTL_MAX_SECONDS,
    LEASE_TTL_SECONDS,
)
from .browser_control_lease_store import (
    LEASE_REFUSAL_CODES,
    BrowserControlLeaseIssuance,
    BrowserControlLeaseProjection,
    BrowserControlLeaseRefusal,
    BrowserControlLeaseStore,
)
from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile
from .local_agent_permissions import (
    DevicePermissionProfile,
    LocalCapability,
    LocalEnforcementResult,
    LocalPermissionRequest,
    evaluate_local_permission,
)

BROWSER_CONTROL_TOOL_ID = "browser.control"

#: #3669 ruling markers, declared as facts rather than left to code reading.
NEW_APPROVAL_STORE = 0
NEW_DURABLE_LEASE_STORE = 1
DESKTOP_DURABLE_LEASE_AUTHORITY = False
DURABLE_RUN_STORE_TOUCHED = False
STEP_UP_EXECUTION = 0
LEASE_RENEWAL_SUPPORTED = False
AUTO_RECOVERY_REAUTHORIZE = False
REPLAY_CANDIDATES = 0
LEASE_ROW_GC = "DEFERRED"
RENDERER_LEASE_MINTING = 0
#: The single canonical owner of "may this session consume a slot".
CANONICAL_LEASE_CONSUME_OWNER = "TRUSTED_AGENT_LEASE_STORE"

#: The closed set of authority-layer (issuance-side) refusal codes. The store's
#: closed set plus these is the complete canonical vocabulary the transport maps.
ISSUANCE_REFUSAL_CODES = (
    "evidence_unavailable",
    "p01_approval_invalid",
    "p01_approval_not_approved",
    "p01_approval_expired",
    "local_policy_denied",
    "lease_issuance_unable",
)


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SAFE_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _digest(value: Any, field_name: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not _SAFE_SHA256_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _origin(value: Any, field_name: str) -> str:
    from .browser_control_actions import MAX_ORIGIN_CHARS, ORIGIN_RE

    origin = value.strip().lower() if isinstance(value, str) else ""
    if not origin or len(origin) > MAX_ORIGIN_CHARS or not ORIGIN_RE.fullmatch(origin):
        raise ContractError(f"{field_name} must be a bounded bare http(s) origin")
    return origin


def _aware(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class BrowserControlLeaseRequest:
    """One trusted `browser.control` session request, bounded like its approval.

    The request fingerprint is the *exact* binding the P01 approval was made
    over: the pause's `invocation_sha256` must equal it, so an approval for a
    different session (origin, budget, window, correlations) can never be
    redeemed here.
    """

    browser_session_ref: str
    run_ref: str
    workspace_ref: str
    owner_ref: str
    device_id: str
    origin_scope: str
    allowed_action_classes: tuple[str, ...]
    ttl_seconds: int = LEASE_TTL_SECONDS
    max_actions: int = LEASE_MAX_ACTIONS

    def __post_init__(self) -> None:
        for field_name in ("browser_session_ref", "run_ref", "workspace_ref", "owner_ref", "device_id"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "origin_scope", _origin(self.origin_scope, "origin_scope"))
        classes = self.allowed_action_classes
        if not isinstance(classes, tuple) or not classes:
            raise ContractError("allowed_action_classes must be a non-empty tuple")
        if len(set(classes)) > len(LEASE_ELIGIBLE_ACTIONS) or any(
            cls not in LEASE_ELIGIBLE_ACTIONS for cls in classes
        ):
            raise ContractError("allowed_action_classes must be a bounded lease-eligible subset")
        object.__setattr__(self, "allowed_action_classes", tuple(sorted(set(classes))))
        if isinstance(self.ttl_seconds, bool) or not isinstance(self.ttl_seconds, int):
            raise ContractError("ttl_seconds must be an integer")
        if not 1 <= self.ttl_seconds <= LEASE_TTL_MAX_SECONDS:
            raise ContractError(f"ttl_seconds must be 1..{LEASE_TTL_MAX_SECONDS}")
        if isinstance(self.max_actions, bool) or not isinstance(self.max_actions, int):
            raise ContractError("max_actions must be an integer")
        if not 1 <= self.max_actions <= LEASE_MAX_ACTIONS_HARD_CAP:
            raise ContractError(f"max_actions must be 1..{LEASE_MAX_ACTIONS_HARD_CAP}")

    @property
    def capability(self) -> LocalCapability:
        return LocalCapability.BROWSER_CONTROL

    def fingerprint(self) -> str:
        """The canonical session-request digest the P01 pause was issued against."""

        payload = {
            "capability": self.capability.value,
            "browser_session_ref": self.browser_session_ref,
            "device_id": self.device_id,
            "origin_scope": self.origin_scope,
            "owner_ref": self.owner_ref,
            "run_ref": self.run_ref,
            "workspace_ref": self.workspace_ref,
            "allowed_action_classes": list(self.allowed_action_classes),
            "ttl_seconds": self.ttl_seconds,
            "max_actions": self.max_actions,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def target_ref(self) -> str:
        """Bounded, URL-free reference for the local permission record."""

        payload = {
            "origin_scope": self.origin_scope,
            "allowed_action_classes": list(self.allowed_action_classes),
            "ttl_seconds": self.ttl_seconds,
            "max_actions": self.max_actions,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "browser_control_" + hashlib.sha256(encoded).hexdigest()[:24]


def browser_control_session_fingerprint(request: BrowserControlLeaseRequest) -> str:
    if not isinstance(request, BrowserControlLeaseRequest):
        raise ContractError("request must be BrowserControlLeaseRequest")
    return request.fingerprint()


@dataclass(frozen=True, slots=True)
class BrowserControlAuthorityEvidence:
    """Authenticated canonical P01 evidence for one exact control session.

    A browser-control-specific *validator/projection* over the existing P01
    evidence envelope (CENTRAL ruling §3): it is not an approval authority —
    the pause/decision objects come from the canonical P01 route, and the
    optional correlation copies (`command_id` / `admission_ref` /
    `revision_ref`) are copied from whatever the canonical evidence carries,
    never minted here.
    """

    evidence_ref: str
    request_fingerprint: str
    permission_request: LocalPermissionRequest
    approval_pause: ApprovalPause
    approval_decision: VerifiedApprovalDecision
    local_policy_ref: str
    expires_at: datetime
    command_id: str | None = None
    admission_ref: str | None = None
    revision_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(
            self, "request_fingerprint", _digest(self.request_fingerprint, "request_fingerprint")
        )
        object.__setattr__(self, "local_policy_ref", _ref(self.local_policy_ref, "local_policy_ref"))
        for optional in ("command_id", "admission_ref", "revision_ref"):
            value = getattr(self, optional)
            if value is not None:
                object.__setattr__(self, optional, _ref(value, optional))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))

        if not isinstance(self.permission_request, LocalPermissionRequest):
            raise ContractError("permission_request must be LocalPermissionRequest")
        if not isinstance(self.approval_pause, ApprovalPause):
            raise ContractError("approval_pause must be canonical ApprovalPause")
        if not isinstance(self.approval_decision, VerifiedApprovalDecision):
            raise ContractError("approval_decision must be canonical VerifiedApprovalDecision")
        if self.permission_request.capability is not LocalCapability.BROWSER_CONTROL:
            raise ContractError("browser control evidence must target the browser.control capability")
        if self.approval_pause.tool_id != BROWSER_CONTROL_TOOL_ID:
            raise ContractError("browser control evidence must target a browser.control pause")
        if self.approval_decision.pause_id != self.approval_pause.pause_id:
            raise ContractError("approval decision does not belong to the supplied pause")
        if self.approval_decision.evidence_ref != self.evidence_ref:
            raise ContractError("approval decision evidence_ref does not match the evidence")
        if self.permission_request.run_id != self.approval_pause.run_id:
            raise ContractError("permission evidence run does not match the approval pause")

        decided_at = _aware(self.approval_decision.decided_at, "approval_decision.decided_at")
        pause_expires_at = _aware(self.approval_pause.expires_at, "approval_pause.expires_at")
        if self.expires_at <= decided_at:
            raise ContractError("browser control evidence expiry must be after the decision")
        if self.expires_at > pause_expires_at:
            raise ContractError("browser control evidence cannot outlive the P01 approval pause")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-browser-control-authority-evidence.v1",
            "evidence_ref": self.evidence_ref,
            "request_fingerprint": self.request_fingerprint,
            "command_id": self.command_id,
            "pause_id": self.approval_pause.pause_id,
            "decision_id": self.approval_decision.decision_id,
            "local_policy_ref": self.local_policy_ref,
            "admission_ref": self.admission_ref,
            "revision_ref": self.revision_ref,
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "raw_url": False,
            "cookie_material": False,
            "credential_material": False,
            "approval_ui_payload": False,
            "page_derived_bytes": 0,
            "client_approval_authority": False,
        }


class BrowserControlAuthorityEvidencePort(Protocol):
    """Trusted boundary that yields authenticated evidence for a fingerprint."""

    def resolve(self, request_fingerprint: str) -> BrowserControlAuthorityEvidence:
        ...


class UnconfiguredBrowserControlEvidencePort:
    """Fails closed when no trusted evidence source is wired."""

    def resolve(self, request_fingerprint: str) -> BrowserControlAuthorityEvidence:
        _digest(request_fingerprint, "request_fingerprint")
        raise BrowserControlLeaseRefusal(
            "evidence_unavailable",
            "no trusted browser control authority evidence source is configured",
        )


class DeterministicBrowserControlEvidencePort:
    """Network-free evidence double for conformance tests only."""

    def __init__(self, evidence: tuple[BrowserControlAuthorityEvidence, ...]) -> None:
        if not isinstance(evidence, tuple) or not evidence:
            raise ContractError("deterministic browser control evidence port requires evidence")
        if not all(isinstance(item, BrowserControlAuthorityEvidence) for item in evidence):
            raise ContractError(
                "deterministic browser control evidence port received invalid evidence"
            )
        by_fingerprint = {item.request_fingerprint: item for item in evidence}
        if len(by_fingerprint) != len(evidence):
            raise ContractError("deterministic browser control evidence fingerprints must be unique")
        self._evidence = by_fingerprint
        self.calls: list[str] = []

    def resolve(self, request_fingerprint: str) -> BrowserControlAuthorityEvidence:
        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        self.calls.append(fingerprint)
        try:
            return self._evidence[fingerprint]
        except KeyError as exc:
            raise BrowserControlLeaseRefusal(
                "evidence_unavailable",
                "no browser control authority evidence exists for this request fingerprint",
            ) from exc


class P01LoopbackBrowserControlEvidenceClient:
    """Consume the **existing** canonical P01 evidence route for a `browser.control`.

    Mirrors the resident process's browser-open / Windows execution evidence
    clients: the same `/v1/broker/p01-evidence` route, the same 4-key request
    body and the same envelope shape. It adds no route and no second
    approval store. Unlike the browser-open client it carries **no** durable
    run-store precondition: the lease row itself is the durable authority for
    this capability, so the `command_id` correlation is an optional copy, not
    a gate.
    """

    def __init__(
        self,
        *,
        base_url: str,
        binding_ref: str,
        request_id: str,
        command_id: str = "",
        opener: Any = None,
    ) -> None:
        self._binding_ref = _ref(binding_ref, "binding_ref")
        self._request_id = _ref(request_id, "request_id")
        if command_id:
            self._command_id = _ref(command_id, "command_id")
        else:
            self._command_id = ""
        self._base_url = base_url.rstrip("/") if isinstance(base_url, str) else ""
        self._opener = opener

    def _fetch(self, fingerprint: str) -> dict[str, Any]:
        body = json.dumps(
            {
                "command_id": self._command_id,
                "binding_ref": self._binding_ref,
                "request_fingerprint": fingerprint,
                "request_id": self._request_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if self._opener is not None:
            payload = self._opener(body)
        elif self._base_url:
            import urllib.request

            request = urllib.request.Request(  # noqa: S310 - fixed loopback boundary
                f"{self._base_url}/v1/broker/p01-evidence",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        else:
            raise BrowserControlLeaseRefusal(
                "evidence_unavailable", "no browser control P01 evidence boundary is configured"
            )
        if not isinstance(payload, dict):
            raise ContractError("the browser control evidence boundary returned no envelope")
        envelope = payload.get("envelope")
        if not isinstance(envelope, dict):
            raise ContractError(
                "the browser control evidence boundary returned no canonical envelope"
            )
        return envelope

    def resolve(self, request_fingerprint: str) -> BrowserControlAuthorityEvidence:
        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        envelope = self._fetch(fingerprint)
        if envelope.get("request_fingerprint") != fingerprint:
            raise ContractError("browser control evidence boundary returned the wrong fingerprint")
        pause_payload = envelope.get("approval_pause")
        decision_payload = envelope.get("approval_decision")
        if not isinstance(pause_payload, dict) or not isinstance(decision_payload, dict):
            raise ContractError(
                "browser control evidence envelope is missing canonical approval objects"
            )
        pause = ApprovalPause(
            pause_id=pause_payload["pause_id"],
            run_id=pause_payload["run_id"],
            agent_runtime_id=pause_payload["agent_runtime_id"],
            tool_id=pause_payload["tool_id"],
            invocation_sha256=pause_payload["invocation_sha256"],
            requirement=ApprovalRequirement(pause_payload["requirement"]),
            step_index=int(pause_payload["step_index"]),
            created_at=datetime.fromisoformat(pause_payload["created_at"]),
            expires_at=datetime.fromisoformat(pause_payload["expires_at"]),
            approval_scope=tuple(pause_payload["approval_scope"]),
        )
        decision = VerifiedApprovalDecision(
            decision_id=decision_payload["decision_id"],
            pause_id=decision_payload["pause_id"],
            outcome=ApprovalOutcome(decision_payload["outcome"]),
            authority_ref=decision_payload["authority_ref"],
            evidence_ref=decision_payload["evidence_ref"],
            decided_at=datetime.fromisoformat(decision_payload["decided_at"]),
        )
        permission_payloads = envelope.get("permission_requests")
        if not isinstance(permission_payloads, list) or len(permission_payloads) != 1:
            raise ContractError("browser control evidence must carry exactly one permission request")
        item = permission_payloads[0]
        if not isinstance(item, dict):
            raise ContractError("browser control evidence permission request is malformed")
        permission_request = LocalPermissionRequest(
            action_id=item["action_id"],
            run_id=item["run_id"],
            device_id=item["device_id"],
            capability=LocalCapability(item["capability"]),
            target_ref=item["target_ref"],
            root_ref=item.get("root_ref"),
        )
        # Correlation copies: taken from the canonical envelope when it carries
        # them, otherwise from the trusted composition context — never minted.
        return BrowserControlAuthorityEvidence(
            evidence_ref=envelope["evidence_ref"],
            request_fingerprint=fingerprint,
            permission_request=permission_request,
            approval_pause=pause,
            approval_decision=decision,
            local_policy_ref=envelope["local_policy_ref"],
            expires_at=datetime.fromisoformat(envelope["expires_at"]),
            command_id=envelope.get("command_id") or (self._command_id or None),
        )


class BrowserControlLeaseAuthority:
    """The trusted agent-side admission authority for bounded control sessions.

    REFUSAL ORDER (every step fails closed):

    1. device correlation with the supplied permission profile;
    2. trusted evidence must exist for this exact request fingerprint;
    3. the evidence must bind this exact session (capability, run, pause
       tool, invocation digest, approval scope);
    4. the canonical P01 decision must be APPROVED and still resumable;
    5. local policy is **recomputed** — a DENY wins even with an approved
       decision;
    6. the TTL expiry is capped by the requested TTL, the evidence expiry and
       the P01 pause expiry — nothing here can extend a lease;
    7. the row lands in the canonical durable store (idempotent).
    """

    def __init__(
        self,
        *,
        device: LocalAgentDeviceProfile,
        permission_profile: DevicePermissionProfile,
        store: BrowserControlLeaseStore,
        evidence_port: BrowserControlAuthorityEvidencePort | None = None,
    ) -> None:
        if not isinstance(device, LocalAgentDeviceProfile):
            raise ContractError("device must be LocalAgentDeviceProfile")
        if not isinstance(permission_profile, DevicePermissionProfile):
            raise ContractError("permission_profile must be DevicePermissionProfile")
        if not isinstance(store, BrowserControlLeaseStore):
            raise ContractError("store must be the canonical BrowserControlLeaseStore")
        if permission_profile.device_id != device.device_id:
            raise ContractError("browser control authority device correlation mismatch")
        if permission_profile.workspace_ref != device.workspace_ref:
            raise ContractError("browser control authority workspace correlation mismatch")
        self._device = device
        self._permission_profile = permission_profile
        self._store = store
        self._evidence_port = evidence_port or UnconfiguredBrowserControlEvidencePort()

    # --- issuance ----------------------------------------------------------

    def issue_from_p01(
        self,
        request: BrowserControlLeaseRequest,
        *,
        now: datetime,
    ) -> tuple[BrowserControlLeaseProjection, bool]:
        """Validate canonical P01 evidence and idempotently land the lease row."""

        if not isinstance(request, BrowserControlLeaseRequest):
            raise ContractError("request must be BrowserControlLeaseRequest")
        moment = _aware(now, "now")
        if request.device_id != self._device.device_id:
            raise BrowserControlLeaseRefusal(
                "lease_correlation_mismatch", "session request device does not match this device"
            )
        if request.workspace_ref != self._device.workspace_ref:
            raise BrowserControlLeaseRefusal(
                "lease_correlation_mismatch", "session request workspace does not match this device"
            )

        fingerprint = request.fingerprint()
        evidence = self._evidence_port.resolve(fingerprint)
        if not isinstance(evidence, BrowserControlAuthorityEvidence):
            raise ContractError("browser control evidence port returned invalid evidence")
        if evidence.request_fingerprint != fingerprint:
            raise BrowserControlLeaseRefusal(
                "p01_approval_invalid", "browser control evidence does not bind this session"
            )
        if evidence.expires_at <= moment:
            raise BrowserControlLeaseRefusal(
                "p01_approval_expired", "the P01 evidence has expired before issuance"
            )
        self._validate_evidence_binding(request=request, evidence=evidence)
        self._validate_p01_approval(request=request, evidence=evidence, now=moment)
        self._recompute_local_policy(evidence=evidence)

        # Expiry cap (CENTRAL ruling §4): requested TTL, canonical evidence
        # expiry and the P01 pause expiry — the minimum of the three, and no
        # local renewal can ever move it later.
        pause_expiry = _aware(evidence.approval_pause.expires_at, "pause.expires_at")
        capped_expiry = min(
            moment + timedelta(seconds=request.ttl_seconds), evidence.expires_at, pause_expiry
        )
        if capped_expiry <= moment:
            raise BrowserControlLeaseRefusal(
                "lease_issuance_unable",
                "the capped lease expiry is not after the issuance moment",
            )
        issuance = BrowserControlLeaseIssuance(
            request_fingerprint=fingerprint,
            browser_session_ref=request.browser_session_ref,
            run_ref=request.run_ref,
            workspace_ref=request.workspace_ref,
            owner_ref=request.owner_ref,
            allowed_action_classes=request.allowed_action_classes,
            origin_scope=request.origin_scope,
            max_actions=request.max_actions,
            issued_at=moment,
            expires_at=capped_expiry,
            approval_ref=evidence.approval_decision.authority_ref,
            evidence_ref=evidence.evidence_ref,
            command_id=evidence.command_id,
            admission_ref=evidence.admission_ref,
            revision_ref=evidence.revision_ref,
        )
        projection, issued = self._store.issue_from_p01(issuance)
        return projection, issued

    def _validate_evidence_binding(
        self, *, request: BrowserControlLeaseRequest, evidence: BrowserControlAuthorityEvidence
    ) -> None:
        permission_request = evidence.permission_request
        if permission_request.run_id != request.run_ref:
            raise BrowserControlLeaseRefusal(
                "p01_approval_invalid",
                "browser control evidence run does not match the session run",
            )
        if permission_request.device_id != request.device_id:
            raise BrowserControlLeaseRefusal(
                "p01_approval_invalid",
                "browser control evidence device does not match the session device",
            )
        if permission_request.target_ref != request.target_ref():
            raise BrowserControlLeaseRefusal(
                "p01_approval_invalid",
                "browser control evidence target does not bind this exact session request",
            )

    @staticmethod
    def _validate_p01_approval(
        *, request: BrowserControlLeaseRequest, evidence: BrowserControlAuthorityEvidence, now: datetime
    ) -> None:
        pause = evidence.approval_pause
        decision = evidence.approval_decision
        if decision.outcome is not ApprovalOutcome.APPROVED:
            raise BrowserControlLeaseRefusal(
                "p01_approval_not_approved", "the canonical P01 decision is not approved"
            )
        if pause.run_id != request.run_ref:
            raise BrowserControlLeaseRefusal(
                "p01_approval_invalid", "the approval pause run does not match the session run"
            )
        if pause.invocation_sha256 != request.fingerprint():
            raise BrowserControlLeaseRefusal(
                "p01_approval_invalid",
                "the P01 approval does not bind this exact control session request",
            )
        if BROWSER_CONTROL_TOOL_ID not in set(pause.approval_scope):
            raise BrowserControlLeaseRefusal(
                "p01_approval_invalid",
                "the P01 approval scope does not cover browser.control",
            )
        try:
            state = resolve_approval_pause(pause, decision, now=now)
        except AgentApprovalError as exc:
            raise BrowserControlLeaseRefusal(
                "p01_approval_invalid", "the canonical P01 browser control approval evidence is invalid"
            ) from exc
        if state.status is not ContinuationStatus.RESUMABLE:
            raise BrowserControlLeaseRefusal(
                "p01_approval_not_approved",
                "the canonical P01 browser control approval is denied or expired",
            )

    def _recompute_local_policy(self, *, evidence: BrowserControlAuthorityEvidence) -> None:
        # DENY wins even with an approved P01 decision: the local policy is
        # recomputed from the profile, never copied from the approval.
        decision = evaluate_local_permission(
            profile=self._permission_profile, request=evidence.permission_request
        )
        if decision.result is LocalEnforcementResult.DENIED:
            raise BrowserControlLeaseRefusal(
                "local_policy_denied", "local policy denied the browser.control session"
            )

    # --- PHASE A: read-only resolve with idempotent lazy issuance ----------

    def resolve_or_issue(
        self,
        request: BrowserControlLeaseRequest,
        *,
        now: datetime,
        provided_fingerprint: str | None = None,
    ) -> BrowserControlLeaseProjection:
        """PHASE A entrypoint for the trusted transport.

        An existing row is returned read-only (any correlation drift or
        expired/revoked/idle fact refuses); a missing row is lazily issued
        from the canonical P01 evidence exactly once. Idempotent: a second
        resolve for the same fingerprint returns the same row and mints
        nothing.

        `provided_fingerprint` is the fingerprint the trusted caller *claims*
        on the wire; it must bind the very session context supplied, or the
        call fails closed (a claimed fingerprint that does not recompute to
        the supplied context is a correlation mismatch, not a guess).
        """

        if not isinstance(request, BrowserControlLeaseRequest):
            raise ContractError("request must be BrowserControlLeaseRequest")
        fingerprint = request.fingerprint()
        if provided_fingerprint is not None:
            claimed = _digest(provided_fingerprint, "provided_fingerprint")
            if claimed != fingerprint:
                raise BrowserControlLeaseRefusal(
                    "lease_correlation_mismatch",
                    "the claimed request fingerprint does not bind this session context",
                )
        existing = self._store.get(fingerprint)
        if existing is not None:
            drifted = [
                name
                for name, supplied in (
                    ("browser_session_ref", request.browser_session_ref),
                    ("run_ref", request.run_ref),
                    ("workspace_ref", request.workspace_ref),
                    ("owner_ref", request.owner_ref),
                    ("allowed_action_classes", request.allowed_action_classes),
                    ("origin_scope", request.origin_scope),
                    ("max_actions", request.max_actions),
                )
                if getattr(existing, name) != supplied
            ]
            if drifted:
                raise BrowserControlLeaseRefusal(
                    "lease_correlation_mismatch",
                    "this request fingerprint is already bound to different "
                    "correlations: " + ", ".join(drifted),
                )
            return self.resolve_lease(
                fingerprint, browser_session_ref=request.browser_session_ref, now=now
            )
        projection, _ = self.issue_from_p01(request, now=now)
        return projection

    def resolve_lease(
        self,
        request_fingerprint: str,
        *,
        browser_session_ref: str,
        now: datetime,
    ) -> BrowserControlLeaseProjection:
        """PHASE A against an already-durable lease: confirm, never mutate."""

        return self._store.resolve_lease(
            request_fingerprint, browser_session_ref=browser_session_ref, now=_aware(now, "now")
        )

    # --- PHASE B: the atomic durable consume ---------------------------------

    def consume_action(
        self,
        request_fingerprint: str,
        *,
        browser_session_ref: str,
        run_ref: str,
        workspace_ref: str,
        owner_ref: str,
        action: str,
        observed_origin: str,
        now: datetime,
    ) -> BrowserControlLeaseProjection:
        """PHASE B: the single owner of one atomic durable slot write."""

        return self._store.consume_action(
            request_fingerprint,
            browser_session_ref=browser_session_ref,
            run_ref=run_ref,
            workspace_ref=workspace_ref,
            owner_ref=owner_ref,
            action=action,
            observed_origin=observed_origin,
            now=_aware(now, "now"),
        )

    # --- the explicit revoke primitive ---------------------------------------

    def revoke_lease(
        self, lease_id: str, *, reason: str, now: datetime
    ) -> BrowserControlLeaseProjection:
        """The explicit durable revoke primitive (no renderer path in this child)."""

        return self._store.revoke_lease(lease_id, reason=reason, now=_aware(now, "now"))

    def get(self, request_fingerprint: str) -> BrowserControlLeaseProjection | None:
        """Read one durable lease by fingerprint. Read-only."""

        return self._store.get(request_fingerprint)


#: The complete closed vocabulary: the store's action-level codes plus the
#: authority's issuance-side codes. The transport maps exactly this set.
CANONICAL_LEASE_REFUSAL_CODES = LEASE_REFUSAL_CODES + ISSUANCE_REFUSAL_CODES
