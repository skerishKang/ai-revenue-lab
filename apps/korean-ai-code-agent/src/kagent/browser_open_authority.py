"""#3611 — real product composition for `browser.open`.

This module is the **callsite** half of #3611. `kagent.browser_open` owns the
open-only contract; this module connects it to the product:

    trusted work ticket
    -> existing `browser.open` capability evaluation (already `ASK`)
    -> canonical P01 approval
    -> one-shot `TrustedBrowserOpenGrant`
    -> trusted host port (Desktop trusted main)
    -> bounded receipt

No new authority is created here:

* the local policy is recomputed with
  ``local_agent_permissions.evaluate_local_permission`` — this module cannot
  widen it;
* the approval is the canonical P01 pair
  (``ApprovalPause`` + ``VerifiedApprovalDecision``) resolved with
  ``padiem_ai_core.agent_approval.resolve_approval_pause`` — this module never
  mints, refreshes or stores a decision;
* the **durable** one-shot is the existing ``DurableRunStore`` (#3082). Its
  ``ADMITTED -> EXECUTING`` transition is the restart-safe fact: a process-local
  consumed set does not survive a Desktop or runner restart, so the authority to
  open is anchored to the durable row instead. No second approval store, no
  second replay set and no new table is introduced.

    BROWSER_OPEN_USES_EXISTING_P01 = True
    SECOND_APPROVAL_AUTHORITY = False
    RESTART_SAFE_ONE_SHOT = True
    NEW_APPROVAL_STORE = False
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import re
import threading
from collections.abc import Callable
from typing import Any, Protocol

from padiem_ai_core.agent_approval import (
    AgentApprovalError,
    ApprovalOutcome,
    ApprovalPause,
    ContinuationStatus,
    VerifiedApprovalDecision,
    resolve_approval_pause,
)

from .browser_open import (
    BROWSER_OPEN_TOOL_ID,
    BrowserOpenGrantConsumer,
    BrowserOpenHostPort,
    BrowserOpenReceipt,
    BrowserOpenRefusal,
    BrowserOpenRequest,
    BrowserOpenOutcome,
    TrustedBrowserOpenGrant,
    UnconfiguredBrowserOpenHostPort,
    authorize_browser_open,
    browser_open_fingerprint,
    browser_open_host_lease_ref,
    browser_open_target_ref,
    run_browser_open,
)
from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile
from .local_agent_durable_run import (
    BoundedEvidenceProjection,
    DurableRunRecord,
    DurableRunState,
    DurableRunTermination,
)
from .local_agent_durable_run_store import DurableRunStore
from .local_agent_permissions import (
    DevicePermissionProfile,
    LocalCapability,
    LocalEnforcementResult,
    LocalPermissionRequest,
    evaluate_local_permission,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

#: Receipt outcomes that mean the admitted command actually ran to a local exit.
_LOADED_OUTCOMES = frozenset({BrowserOpenOutcome.LOADED})


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _digest(value: Any, field_name: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _aware(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class BrowserOpenAuthorityEvidence:
    """Authenticated P01 + admission evidence for one exact browser open.

    Mirrors ``TrustedP01WindowsExecutionEvidenceEnvelope``: it carries the
    canonical Core approval objects, the exact command fingerprint and the
    durable admission correlation. Raw URLs, cookies, credentials and approval
    UI payloads are absent by construction.
    """

    evidence_ref: str
    request_fingerprint: str
    #: The durable admission this open belongs to. This is the restart-safe
    #: anchor: the one-shot is decided by this row's durable state, not by any
    #: in-process set.
    command_id: str
    permission_request: LocalPermissionRequest
    approval_pause: ApprovalPause
    approval_decision: VerifiedApprovalDecision
    local_policy_ref: str
    admission_ref: str
    revision_ref: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(
            self, "request_fingerprint", _digest(self.request_fingerprint, "request_fingerprint")
        )
        object.__setattr__(self, "command_id", _ref(self.command_id, "command_id"))
        object.__setattr__(self, "local_policy_ref", _ref(self.local_policy_ref, "local_policy_ref"))
        object.__setattr__(self, "admission_ref", _ref(self.admission_ref, "admission_ref"))
        object.__setattr__(self, "revision_ref", _ref(self.revision_ref, "revision_ref"))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))

        if not isinstance(self.permission_request, LocalPermissionRequest):
            raise ContractError("permission_request must be LocalPermissionRequest")
        if not isinstance(self.approval_pause, ApprovalPause):
            raise ContractError("approval_pause must be canonical ApprovalPause")
        if not isinstance(self.approval_decision, VerifiedApprovalDecision):
            raise ContractError("approval_decision must be canonical VerifiedApprovalDecision")
        if self.permission_request.capability is not LocalCapability.BROWSER_OPEN:
            raise ContractError("browser open evidence must target the browser.open capability")
        if self.approval_pause.tool_id != BROWSER_OPEN_TOOL_ID:
            raise ContractError("browser open evidence must target a browser.open pause")
        if self.approval_decision.pause_id != self.approval_pause.pause_id:
            raise ContractError("approval decision does not belong to the supplied pause")
        if self.approval_decision.evidence_ref != self.evidence_ref:
            raise ContractError("approval decision evidence_ref does not match the evidence")
        if self.permission_request.run_id != self.approval_pause.run_id:
            raise ContractError("permission evidence run does not match the approval pause")

        decided_at = _aware(self.approval_decision.decided_at, "approval_decision.decided_at")
        pause_expires_at = _aware(self.approval_pause.expires_at, "approval_pause.expires_at")
        if self.expires_at <= decided_at:
            raise ContractError("browser open evidence expiry must be after the decision")
        if self.expires_at > pause_expires_at:
            raise ContractError("browser open evidence cannot outlive the P01 approval pause")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-browser-open-authority-evidence.v1",
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


class BrowserOpenAuthorityEvidencePort(Protocol):
    """Trusted boundary that yields authenticated evidence for a fingerprint."""

    def resolve(self, request_fingerprint: str) -> BrowserOpenAuthorityEvidence:
        ...


class UnconfiguredBrowserOpenAuthorityEvidencePort:
    """Fails closed when no trusted evidence source is wired."""

    def resolve(self, request_fingerprint: str) -> BrowserOpenAuthorityEvidence:
        _digest(request_fingerprint, "request_fingerprint")
        raise BrowserOpenRefusal(
            "evidence_unavailable",
            "no trusted browser open authority evidence source is configured",
        )


class DeterministicBrowserOpenAuthorityEvidencePort:
    """Network-free evidence double for conformance tests only."""

    def __init__(self, evidence: tuple[BrowserOpenAuthorityEvidence, ...]) -> None:
        if not isinstance(evidence, tuple) or not evidence:
            raise ContractError("deterministic browser open evidence port requires evidence")
        if not all(isinstance(item, BrowserOpenAuthorityEvidence) for item in evidence):
            raise ContractError("deterministic browser open evidence port received invalid evidence")
        by_fingerprint = {item.request_fingerprint: item for item in evidence}
        if len(by_fingerprint) != len(evidence):
            raise ContractError("deterministic browser open evidence fingerprints must be unique")
        self._evidence = by_fingerprint
        self.calls: list[str] = []

    def resolve(self, request_fingerprint: str) -> BrowserOpenAuthorityEvidence:
        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        self.calls.append(fingerprint)
        try:
            return self._evidence[fingerprint]
        except KeyError as exc:
            raise BrowserOpenRefusal(
                "evidence_unavailable",
                "no browser open authority evidence exists for this request fingerprint",
            ) from exc


class P01LoopbackBrowserOpenEvidenceClient:
    """Consume the **existing** canonical P01 evidence route for a `browser.open`.

    This mirrors the resident process's Windows execution evidence client exactly:
    the same ``/v1/broker/p01-evidence`` route, the same 4-key request body and the
    same envelope shape. It adds no route, no server authority and no second
    approval store — the owner lane already decides the canonical APPROVED pause.

    The durable admission correlation (`admission_ref`, `revision_ref`) is read
    from the existing #3082 row for the same command, so the evidence can never
    describe a different admission than the one the durable one-shot guards.
    """

    def __init__(
        self,
        *,
        store: DurableRunStore,
        command_id: str,
        binding_ref: str,
        request_id: str,
        base_url: str = "",
        opener: Any = None,
    ) -> None:
        if not isinstance(store, DurableRunStore):
            raise ContractError("store must be the canonical DurableRunStore")
        self._store = store
        self._command_id = _ref(command_id, "command_id")
        self._binding_ref = _ref(binding_ref, "binding_ref")
        self._request_id = _ref(request_id, "request_id")
        self._base_url = base_url.rstrip("/") if isinstance(base_url, str) else ""
        self._opener = opener

    def _fetch(self, fingerprint: str) -> dict[str, Any]:
        import json as _json
        import urllib.request

        body = _json.dumps(
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
            request = urllib.request.Request(  # noqa: S310 - fixed loopback boundary
                f"{self._base_url}/v1/broker/p01-evidence",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                payload = _json.loads(response.read().decode("utf-8"))
        else:
            raise BrowserOpenRefusal(
                "evidence_unavailable", "no browser open P01 evidence boundary is configured"
            )
        if not isinstance(payload, dict):
            raise ContractError("the browser open evidence boundary returned no envelope")
        envelope = payload.get("envelope")
        if not isinstance(envelope, dict):
            raise ContractError("the browser open evidence boundary returned no canonical envelope")
        return envelope

    def resolve(self, request_fingerprint: str) -> BrowserOpenAuthorityEvidence:
        from padiem_ai_core.agent_approval import ApprovalRequirement

        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        record = self._store.get(command_id=self._command_id)
        if record is None:
            raise BrowserOpenRefusal(
                "command_not_admitted",
                "browser open evidence requires an already-admitted durable command",
            )
        if record.admission_ref is None:
            raise BrowserOpenRefusal(
                "command_not_admitted",
                "browser open evidence requires a durably admitted command",
            )
        envelope = self._fetch(fingerprint)
        if envelope.get("request_fingerprint") != fingerprint:
            raise ContractError("browser open evidence boundary returned the wrong fingerprint")
        pause_payload = envelope.get("approval_pause")
        decision_payload = envelope.get("approval_decision")
        if not isinstance(pause_payload, dict) or not isinstance(decision_payload, dict):
            raise ContractError("browser open evidence envelope is missing canonical approval objects")
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
            raise ContractError("browser open evidence must carry exactly one permission request")
        item = permission_payloads[0]
        if not isinstance(item, dict):
            raise ContractError("browser open evidence permission request is malformed")
        permission_request = LocalPermissionRequest(
            action_id=item["action_id"],
            run_id=item["run_id"],
            device_id=item["device_id"],
            capability=LocalCapability(item["capability"]),
            target_ref=item["target_ref"],
            root_ref=item.get("root_ref"),
        )
        return BrowserOpenAuthorityEvidence(
            evidence_ref=envelope["evidence_ref"],
            request_fingerprint=fingerprint,
            command_id=record.command_id,
            permission_request=permission_request,
            approval_pause=pause,
            approval_decision=decision,
            local_policy_ref=envelope["local_policy_ref"],
            admission_ref=record.admission_ref,
            revision_ref=record.revision_ref,
            expires_at=datetime.fromisoformat(envelope["expires_at"]),
        )


class P01LocalPermissionBrowserOpenAuthorizationPort:
    """Issue a one-shot `browser.open` grant from canonical P01 + durable admission.

    Refusal order is the contract, and every step fails closed:

    1. device correlation with the supplied permission profile;
    2. trusted evidence must exist for this exact request fingerprint;
    3. the evidence must bind this exact request (capability, action, target ref);
    4. the canonical P01 decision must be APPROVED, in scope and still resumable;
    5. local policy is **recomputed** — a DENY wins even with an approved decision;
    6. the durable admission must exist, still be ``ADMITTED``, and still be inside
       its hard deadline.

    Step 6 is a **read-only precondition**. The ``ADMITTED -> EXECUTING`` write is
    deliberately *not* here: it happens exactly once, later, in :meth:`redeem`, so
    there is a single owner of the durable transition and a single place where a
    concurrent replay can be resolved.

        ADMITTED_TO_EXECUTING_OWNER=CANONICAL_BROWSER_OPEN_REDEMPTION
        DURABLE_TRANSITION_COUNT_MAX=1

    The in-process consumed sets are only a cheap fast path and are explicitly
    **not** the authority.
    """

    def __init__(
        self,
        *,
        device: LocalAgentDeviceProfile,
        permission_profile: DevicePermissionProfile,
        store: DurableRunStore,
        evidence_port: BrowserOpenAuthorityEvidencePort | None = None,
    ) -> None:
        if not isinstance(device, LocalAgentDeviceProfile):
            raise ContractError("device must be LocalAgentDeviceProfile")
        if not isinstance(permission_profile, DevicePermissionProfile):
            raise ContractError("permission_profile must be DevicePermissionProfile")
        if not isinstance(store, DurableRunStore):
            raise ContractError("store must be the canonical DurableRunStore")
        # The device and the local policy must describe the same machine, or the
        # recomputed decision below would be about a different device than the
        # grant claims.
        if permission_profile.device_id != device.device_id:
            raise ContractError("browser open authority device correlation mismatch")
        if permission_profile.workspace_ref != device.workspace_ref:
            raise ContractError("browser open authority workspace correlation mismatch")
        self._device = device
        self._permission_profile = permission_profile
        self._store = store
        self._evidence_port = evidence_port or UnconfiguredBrowserOpenAuthorityEvidencePort()
        self._consumed_fingerprints: set[str] = set()
        self._consumed_decisions: set[str] = set()
        # Authorized-but-not-yet-redeemed opens, keyed by the durable command.
        # This is what lets a redemption verify that the Desktop is redeeming an
        # open this agent actually authorized, instead of trusting a bare id.
        self._pending: dict[str, tuple[str, str, str]] = {}
        self._lock = threading.Lock()

    @property
    def consumed_count(self) -> int:
        return len(self._consumed_fingerprints)

    def authorize(
        self, *, request: BrowserOpenRequest, now: datetime
    ) -> tuple[TrustedBrowserOpenGrant, BrowserOpenAuthorityEvidence]:
        if not isinstance(request, BrowserOpenRequest):
            raise ContractError("request must be BrowserOpenRequest")
        now = _aware(now, "now")
        if self._permission_profile.device_id != request.device_id:
            raise ContractError("browser open permission profile device mismatch")

        fingerprint = browser_open_fingerprint(request)
        evidence = self._evidence_port.resolve(fingerprint)
        if not isinstance(evidence, BrowserOpenAuthorityEvidence):
            raise ContractError("browser open evidence port returned invalid evidence")
        if evidence.request_fingerprint != fingerprint:
            raise ContractError("browser open evidence fingerprint mismatch")
        if evidence.expires_at <= now:
            raise BrowserOpenRefusal("grant_rejected", "browser open evidence has expired")

        self._validate_permission_request(request=request, evidence=evidence)
        decision = evaluate_local_permission(
            profile=self._permission_profile, request=evidence.permission_request
        )
        if decision.result is LocalEnforcementResult.DENIED:
            raise BrowserOpenRefusal("policy_denied", "local policy denied browser.open")
        if (
            decision.capability is not LocalCapability.BROWSER_OPEN
            or decision.action_id != evidence.permission_request.action_id
        ):
            raise ContractError("recomputed local browser.open decision correlation mismatch")

        self._validate_p01_approval(request=request, evidence=evidence, now=now)

        with self._lock:
            if fingerprint in self._consumed_fingerprints:
                raise BrowserOpenRefusal(
                    "grant_rejected", "browser open request fingerprint has already been consumed"
                )
            if evidence.approval_decision.decision_id in self._consumed_decisions:
                raise BrowserOpenRefusal(
                    "grant_rejected", "canonical P01 decision has already been consumed"
                )

        # Read-only durable precondition. No write happens here — the single
        # transition belongs to `redeem`.
        self._require_admitted_command(
            command_id=evidence.command_id,
            request=request,
            now=now,
        )

        grant = authorize_browser_open(
            request=request,
            profile=self._permission_profile,
            device=self._device,
            pause=evidence.approval_pause,
            decision=evidence.approval_decision,
            now=now,
            host_lease_ref=browser_open_host_lease_ref(request),
        )
        with self._lock:
            self._consumed_fingerprints.add(fingerprint)
            self._consumed_decisions.add(evidence.approval_decision.decision_id)
            self._pending[evidence.command_id] = (
                grant.request_fingerprint,
                grant.open_id,
                grant.run_id,
            )
        return grant, evidence

    def redeem(
        self,
        *,
        redemption_ref: str,
        request_fingerprint: str,
        open_id: str,
        run_ref: str,
        now: datetime,
    ) -> None:
        """The one and only ``ADMITTED -> EXECUTING`` transition.

        Called from the trusted boundary that owns the browser (the Desktop
        trusted main, through the existing supervised resident pipe) immediately
        before a view may exist. Two concurrent callers cannot both succeed: the
        decision is one SQLite transaction, so the loser is refused.
        """

        moment = _aware(now, "now")
        command_id = _ref(redemption_ref, "redemption_ref")
        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        open_id = _id(open_id, "open_id")
        run_ref = _ref(run_ref, "run_ref")

        with self._lock:
            pending = self._pending.get(command_id)
        if pending != (fingerprint, open_id, run_ref):
            # Never redeem a command this agent did not authorize for exactly
            # this open. A bare id is not authorization.
            raise BrowserOpenRefusal(
                "redemption_not_authorized",
                "browser open redemption does not match an authorized open",
            )

        # Correlation only above; the durable row is the authority here.
        self._transition_to_executing(command_id=command_id, now=moment)

    def _transition_to_executing(self, *, command_id: str, now: datetime) -> DurableRunRecord:
        """The single durable write. Refuses unless the row is still ADMITTED."""

        record = self._store.get(command_id=command_id)
        if record is None:
            raise BrowserOpenRefusal(
                "command_not_admitted",
                "browser open requires an already-admitted durable command",
            )
        if record.state is DurableRunState.TERMINAL:
            raise BrowserOpenRefusal(
                "command_already_settled",
                "browser open command has already reached a durable terminal outcome",
            )
        if record.state is not DurableRunState.ADMITTED:
            # The restart-safe denial: this command's single local run has already
            # begun, durably, in this process or a previous one.
            raise BrowserOpenRefusal(
                "command_already_started",
                "browser open command has already started its single local run",
            )
        if record.hard_deadline_passed(now=now):
            raise BrowserOpenRefusal("command_expired", "browser open command hard deadline passed")
        if now < record.admitted_at:
            raise BrowserOpenRefusal(
                "command_not_admitted", "browser open command is not yet admitted"
            )
        if not self._store.mark_started(command_id=command_id, started_at=now):
            # Lost the race between the read and the write.
            raise BrowserOpenRefusal(
                "command_already_started",
                "browser open command has already started its single local run",
            )
        started = self._store.get(command_id=command_id)
        if started is None:  # pragma: no cover - the write above just succeeded
            raise ContractError("durable browser open command disappeared after mark_started")
        return started

    def _require_admitted_command(
        self,
        *,
        command_id: str,
        request: BrowserOpenRequest,
        now: datetime,
    ) -> DurableRunRecord:
        """Read-only durable precondition. Performs no write at all."""

        record = self._store.get(command_id=command_id)
        if record is None:
            raise BrowserOpenRefusal(
                "command_not_admitted",
                "browser open requires an already-admitted durable command",
            )
        if record.run_id != request.run_id or record.device_id != request.device_id:
            raise ContractError("durable browser open command correlation mismatch")
        if record.state is DurableRunState.TERMINAL:
            raise BrowserOpenRefusal(
                "command_already_settled",
                "browser open command has already reached a durable terminal outcome",
            )
        if record.state is not DurableRunState.ADMITTED:
            raise BrowserOpenRefusal(
                "command_already_started",
                "browser open command has already started its single local run",
            )
        # R6 and record invariants are checked here so the later write can never
        # persist a row the store would refuse to load back.
        if record.hard_deadline_passed(now=now):
            raise BrowserOpenRefusal("command_expired", "browser open command hard deadline passed")
        if now < record.admitted_at:
            raise BrowserOpenRefusal("command_not_admitted", "browser open command is not yet admitted")
        return record

    @staticmethod
    def _validate_permission_request(
        *, request: BrowserOpenRequest, evidence: BrowserOpenAuthorityEvidence
    ) -> None:
        permission_request = evidence.permission_request
        if permission_request.device_id != request.device_id:
            raise ContractError("browser open permission evidence device mismatch")
        if permission_request.run_id != request.run_id:
            raise ContractError("browser open permission evidence run mismatch")
        if permission_request.action_id != f"browser_open_{request.open_id}":
            raise ContractError("browser open permission evidence action mismatch")
        if permission_request.target_ref != browser_open_target_ref(request):
            raise ContractError("browser open permission evidence is not bound to this URL")

    @staticmethod
    def _validate_p01_approval(
        *, request: BrowserOpenRequest, evidence: BrowserOpenAuthorityEvidence, now: datetime
    ) -> None:
        pause = evidence.approval_pause
        decision = evidence.approval_decision
        if decision.outcome is not ApprovalOutcome.APPROVED:
            raise BrowserOpenRefusal("grant_rejected", "canonical P01 decision is not approved")
        if pause.tool_id != BROWSER_OPEN_TOOL_ID:
            raise ContractError("approval pause is not a browser.open pause")
        if pause.run_id != request.run_id:
            raise ContractError("approval pause run does not match the browser open run")
        if pause.invocation_sha256 != browser_open_fingerprint(request):
            raise BrowserOpenRefusal(
                "grant_rejected", "approval does not bind this exact browser open request"
            )
        if LocalCapability.BROWSER_OPEN.value not in set(pause.approval_scope):
            raise ContractError("P01 browser open approval scope does not cover browser.open")
        try:
            state = resolve_approval_pause(pause, decision, now=now)
        except AgentApprovalError as exc:
            raise BrowserOpenRefusal(
                "grant_rejected", "canonical P01 browser open approval evidence is invalid"
            ) from exc
        if state.status is not ContinuationStatus.RESUMABLE:
            raise BrowserOpenRefusal(
                "grant_rejected", "canonical P01 browser open approval is denied or expired"
            )


def settle_browser_open_command(
    *,
    store: DurableRunStore,
    command_id: str,
    receipt: BrowserOpenReceipt,
    now: datetime,
) -> bool:
    """Persist the durable terminal outcome for a completed browser open.

    Completing the existing state machine keeps the durable row truthful and keeps
    the recovery path meaningful. It is **not** a replay decision: the row moves to
    ``TERMINAL``, which ``NON_REPLAYABLE_STATES`` already covers, so a later open is
    still refused rather than re-executed.
    """

    if not isinstance(store, DurableRunStore):
        raise ContractError("store must be the canonical DurableRunStore")
    if not isinstance(receipt, BrowserOpenReceipt):
        raise ContractError("receipt must be BrowserOpenReceipt")
    moment = _aware(now, "now")
    record = store.get(command_id=command_id)
    if record is None:
        raise ContractError("browser open settlement requires an admitted durable command")
    if record.started_at is None:
        raise ContractError("browser open settlement requires a durably started command")
    if record.terminal:
        # A durable terminal outcome is never overwritten.
        return False
    termination = (
        DurableRunTermination.EXITED
        if receipt.load_outcome in _LOADED_OUTCOMES
        else DurableRunTermination.ABORTED
    )
    digest = hashlib.sha256(
        f"{receipt.open_id}:{receipt.load_outcome.value}:{command_id}".encode("utf-8")
    ).hexdigest()[:24]
    terminal = replace(
        record,
        state=DurableRunState.TERMINAL,
        termination=termination,
        terminated_at=max(moment, record.started_at),
        exit_code=None,
        evidence=BoundedEvidenceProjection(
            evidence_ref=f"browser_open_receipt_{digest}",
            item_count=0,
            summary=f"browser.open {receipt.load_outcome.value}",
        ),
    )
    store.record_terminal(terminal)
    return True


@dataclass(frozen=True, slots=True)
class BrowserOpenAuthorityOutcome:
    """One composed `browser.open`: the grant, the receipt and the durable anchor."""

    open_id: str
    run_id: str
    device_id: str
    command_id: str
    evidence_ref: str
    host_lease_ref: str
    load_outcome: BrowserOpenOutcome
    redirect_count: int
    settled: bool
    receipt: BrowserOpenReceipt

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-browser-open-authority-outcome.v1",
            "open_id": self.open_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "command_id": self.command_id,
            "evidence_ref": self.evidence_ref,
            "host_lease_ref": self.host_lease_ref,
            "load_outcome": self.load_outcome.value,
            "redirect_count": self.redirect_count,
            "settled": self.settled,
            "receipt": self.receipt.safe_dict(),
            "second_approval_authority": False,
            "second_browser_authority": False,
            "page_derived_bytes": 0,
        }


class BrowserOpenAuthority:
    """The real caller: capability -> canonical P01 -> one-shot grant -> host.

    It owns no Electron API and mints no authority. The trusted host arrives
    through ``BrowserOpenHostPort`` (in the product, the Desktop trusted main).
    """

    def __init__(
        self,
        *,
        device: LocalAgentDeviceProfile,
        permission_profile: DevicePermissionProfile,
        store: DurableRunStore,
        host: BrowserOpenHostPort | None = None,
        evidence_port: BrowserOpenAuthorityEvidencePort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(device, LocalAgentDeviceProfile):
            raise ContractError("device must be LocalAgentDeviceProfile")
        if not isinstance(permission_profile, DevicePermissionProfile):
            raise ContractError("permission_profile must be DevicePermissionProfile")
        if permission_profile.device_id != device.device_id:
            raise ContractError("browser open authority device correlation mismatch")
        if permission_profile.workspace_ref != device.workspace_ref:
            raise ContractError("browser open authority workspace correlation mismatch")
        if {item.root_ref for item in permission_profile.roots} != {
            item.root_ref for item in device.roots
        }:
            raise ContractError("browser open authority permission roots must match device roots")
        self._device = device
        self._permission_profile = permission_profile
        self._store = store
        self._host = host or UnconfiguredBrowserOpenHostPort()
        self._authorization = P01LocalPermissionBrowserOpenAuthorizationPort(
            device=device,
            permission_profile=permission_profile,
            store=store,
            evidence_port=evidence_port,
        )
        self._consumer = BrowserOpenGrantConsumer()
        # The transport carries no timestamp, so the redemption reads the clock
        # here. Injectable so a caller (and a test) can pin it.
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def workspace_ref(self) -> str:
        return self._device.workspace_ref

    @property
    def consumed_count(self) -> int:
        return self._consumer.consumed_count

    def authorize(
        self, *, request: BrowserOpenRequest, now: datetime
    ) -> TrustedBrowserOpenGrant:
        """Authorize one open **without** consuming the durable transition.

        This is the agent half of the two-sided product topology: the agent
        authorizes and mints the one-shot grant, and the Desktop must then redeem
        before it may create a view. :meth:`open` composes the same two steps in
        one process for an in-process caller.
        """

        if not isinstance(request, BrowserOpenRequest):
            raise ContractError("request must be BrowserOpenRequest")
        moment = _aware(now, "now")
        if request.device_id != self._device.device_id:
            raise ContractError("browser open request device mismatch")
        grant, _ = self._authorization.authorize(request=request, now=moment)
        return grant

    def redeem_transport(
        self,
        *,
        redemption_ref: str,
        request_fingerprint: str,
        open_id: str,
        run_ref: str,
        now: datetime | None = None,
    ) -> None:
        """Redemption entry point for the supervised resident transport.

        This is the whole server side of ``browser_open_redemption``: it takes
        exactly the correlation the Desktop port needs, performs the one atomic
        durable transition, and returns nothing. The Desktop then owns the view;
        the durable fact stays here.
        """

        moment = _aware(now, "now") if now is not None else _aware(self._clock(), "clock")
        self._authorization.redeem(
            redemption_ref=redemption_ref,
            request_fingerprint=request_fingerprint,
            open_id=open_id,
            run_ref=run_ref,
            now=moment,
        )

    def redemption_callable(self) -> Any:
        """The exact callable the bounded dispatcher invokes for its second kind."""

        return self.redeem_transport

    def open(self, *, request: BrowserOpenRequest, now: datetime) -> BrowserOpenAuthorityOutcome:
        if not isinstance(request, BrowserOpenRequest):
            raise ContractError("request must be BrowserOpenRequest")
        moment = _aware(now, "now")
        if request.device_id != self._device.device_id:
            raise ContractError("browser open request device mismatch")

        grant, evidence = self._authorization.authorize(request=request, now=moment)
        # The single durable transition, immediately before anything can open.
        self._authorization.redeem(
            redemption_ref=evidence.command_id,
            request_fingerprint=grant.request_fingerprint,
            open_id=grant.open_id,
            run_ref=grant.run_id,
            now=moment,
        )
        try:
            receipt = run_browser_open(
                request=request,
                grant=grant,
                consumer=self._consumer,
                host=self._host,
                now=moment,
            )
        except BrowserOpenRefusal:
            # Nothing was opened, but the command *did* begin durably. Recording an
            # abort keeps the row truthful instead of leaving it EXECUTING forever;
            # it stays non-replayable either way.
            _settle_aborted_command(
                store=self._store, command_id=evidence.command_id, occurred_at=moment
            )
            raise
        settled = settle_browser_open_command(
            store=self._store,
            command_id=evidence.command_id,
            receipt=receipt,
            now=moment,
        )
        return BrowserOpenAuthorityOutcome(
            open_id=request.open_id,
            run_id=request.run_id,
            device_id=request.device_id,
            command_id=evidence.command_id,
            evidence_ref=evidence.evidence_ref,
            host_lease_ref=grant.host_lease_ref,
            load_outcome=receipt.load_outcome,
            redirect_count=receipt.redirect_count,
            settled=settled,
            receipt=receipt,
        )


def _settle_aborted_command(
    *, store: DurableRunStore, command_id: str, occurred_at: datetime
) -> bool:
    record = store.get(command_id=command_id)
    if record is None or record.terminal or record.started_at is None:
        return False
    terminal = replace(
        record,
        state=DurableRunState.TERMINAL,
        termination=DurableRunTermination.ABORTED,
        terminated_at=max(occurred_at, record.started_at),
        exit_code=None,
        evidence=BoundedEvidenceProjection(
            evidence_ref="browser_open_aborted",
            item_count=0,
            summary="browser.open aborted before a receipt",
        ),
    )
    store.record_terminal(terminal)
    return True


BROWSER_OPEN_AUTHORITY_COMPOSED = True
BROWSER_OPEN_USES_EXISTING_P01 = True
SECOND_APPROVAL_AUTHORITY = False
SECOND_BROWSER_AUTHORITY = False
BROWSER_CONTROL_IMPLEMENTED = False
RESTART_SAFE_ONE_SHOT = True
NEW_APPROVAL_STORE = False
DURABLE_ONE_SHOT_ANCHOR = "durable_run_store_admitted_to_executing"
LOCAL_POLICY_RECOMPUTED_AT_COMPOSITION = True
PAGE_DERIVED_BYTES = 0
P01_EVIDENCE_ROUTE_REUSED = "/v1/broker/p01-evidence"
NEW_BROKER_ROUTE = False
CONCRETE_EVIDENCE_CLIENT_IMPLEMENTED = True

#: The durable one-shot has exactly one owner: the redemption step, which is the
#: step the Desktop must pass through before a view may exist.
ADMITTED_TO_EXECUTING_OWNER = "CANONICAL_BROWSER_OPEN_REDEMPTION"
DURABLE_TRANSITION_COUNT_MAX = 1
AUTHORIZE_PERFORMS_DURABLE_WRITE = False
REDEMPTION_VERIFIES_AN_AUTHORIZED_OPEN = True
