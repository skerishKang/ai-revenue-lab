from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from .cloud_execution_plan import CloudM1ExecutionPlan, CloudM1Stage
from .cloud_stage_receipts import CloudM1StageReceipt, CloudStageOutcome
from .contracts import ContractError, SandboxLease, SandboxLeaseState
from .sandbox import SandboxLeaseError
from .sandbox_artifact_collection import ArtifactCandidateCollection
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TrustedTeardownObservation:
    observation_id: str
    plan_id: str
    run_id: str
    sandbox_lease_ref: str
    computer_ref: str | None
    observed_at: datetime
    process_tree_killed: bool
    active_child_process_count: int
    workspace_destroyed: bool
    sandbox_terminal: bool
    computer_terminal: bool
    preview_shares_terminal: bool
    human_control_terminal: bool
    artifacts_finalized: bool
    authority_ref: str

    def __post_init__(self) -> None:
        for field_name in ("observation_id", "plan_id", "run_id", "sandbox_lease_ref", "authority_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if self.computer_ref is not None:
            object.__setattr__(self, "computer_ref", _ref(self.computer_ref, "computer_ref"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        for field_name in (
            "process_tree_killed",
            "workspace_destroyed",
            "sandbox_terminal",
            "computer_terminal",
            "preview_shares_terminal",
            "human_control_terminal",
            "artifacts_finalized",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ContractError(f"{field_name} must be boolean")
        if isinstance(self.active_child_process_count, bool) or not isinstance(self.active_child_process_count, int) or not 0 <= self.active_child_process_count <= 1_000_000:
            raise ContractError("active_child_process_count must be a non-negative bounded integer")
        if self.computer_ref is None and self.computer_terminal is not True:
            raise ContractError("computer_terminal must be true when no Agent Computer was allocated")

    @property
    def clean(self) -> bool:
        return (
            self.process_tree_killed
            and self.active_child_process_count == 0
            and self.workspace_destroyed
            and self.sandbox_terminal
            and self.computer_terminal
            and self.preview_shares_terminal
            and self.human_control_terminal
            and self.artifacts_finalized
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "sandbox_lease_ref": self.sandbox_lease_ref,
            "computer_ref": self.computer_ref,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "process_tree_killed": self.process_tree_killed,
            "active_child_process_count": self.active_child_process_count,
            "workspace_destroyed": self.workspace_destroyed,
            "sandbox_terminal": self.sandbox_terminal,
            "computer_terminal": self.computer_terminal,
            "preview_shares_terminal": self.preview_shares_terminal,
            "human_control_terminal": self.human_control_terminal,
            "artifacts_finalized": self.artifacts_finalized,
            "authority_ref": self.authority_ref,
            "clean": self.clean,
            "raw_runtime_payload": False,
            "provider_endpoint": False,
            "credential_value": False,
        }


# A lease in one of these states is no longer serving a run. That is all this
# module can conclude from it: terminality is not proof that a process tree died,
# which stays a separate, still-unimplemented contract (#2783 non-goal).
LEASE_TERMINAL_STATES = frozenset(
    {SandboxLeaseState.RELEASED, SandboxLeaseState.EXPIRED}
)
LEASE_TERMINAL_STATE_TOKENS = frozenset(state.value.upper() for state in LEASE_TERMINAL_STATES)


@dataclass(frozen=True, slots=True)
class TeardownVerification:
    """What the teardown boundary could check for itself, apart from attestation.

    Kept separate from ``TrustedTeardownObservation`` on purpose: the observation
    records what a caller says it saw, and this records what this module could
    re-derive from a lease lookup and the bounded artifact collection.
    """

    lease_resolved: bool
    lease_state: str
    lease_run_matches: bool
    artifact_collection_id: str | None
    artifact_run_matches: bool
    artifact_lease_matches: bool

    @property
    def lease_terminal(self) -> bool:
        return bool(
            self.lease_resolved
            and self.lease_run_matches
            and self.lease_state in LEASE_TERMINAL_STATE_TOKENS
        )

    @property
    def artifacts_finalized_verified(self) -> bool:
        return bool(
            self.artifact_collection_id
            and self.artifact_run_matches
            and self.artifact_lease_matches
        )

    def blocking_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.lease_resolved:
            reasons.append("LEASE_UNRESOLVED")
        elif not self.lease_run_matches:
            reasons.append("LEASE_RUN_MISMATCH")
        elif not self.lease_terminal:
            reasons.append("LEASE_NOT_TERMINAL")
        if self.artifact_collection_id is None:
            reasons.append("ARTIFACT_COLLECTION_ABSENT")
        elif not self.artifact_run_matches:
            reasons.append("ARTIFACT_COLLECTION_RUN_MISMATCH")
        elif not self.artifact_lease_matches:
            reasons.append("ARTIFACT_COLLECTION_LEASE_MISMATCH")
        return tuple(reasons)


def verify_teardown_evidence(
    *,
    observation: TrustedTeardownObservation,
    lease_lookup: Any,
    artifact_collection: Any,
) -> TeardownVerification:
    """Resolve the lease and artifact evidence a teardown receipt must check.

    ``lease_lookup`` is an injected ``lease_ref -> SandboxLease | None`` reader. It
    is a parameter rather than an import of any provider so that this module
    performs no dispatch, network, or filesystem work of its own, and the caller
    keeps the authority dependency explicit.

    A lookup that reports an unknown lease (``SandboxLeaseError``) is recorded as
    unresolved, not swallowed silently: it still blocks a clean verdict.
    """
    if not isinstance(observation, TrustedTeardownObservation):
        raise ContractError("observation must be TrustedTeardownObservation")
    if not callable(lease_lookup):
        raise ContractError("lease_lookup must be a callable lease reference resolver")
    if artifact_collection is not None and not isinstance(
        artifact_collection, ArtifactCandidateCollection
    ):
        raise ContractError("artifact_collection must be ArtifactCandidateCollection")

    lease: SandboxLease | None = None
    try:
        resolved = lease_lookup(observation.sandbox_lease_ref)
    except SandboxLeaseError:
        resolved = None
    if resolved is not None and not isinstance(resolved, SandboxLease):
        raise ContractError("lease_lookup must return SandboxLease or None")
    lease = resolved

    return TeardownVerification(
        lease_resolved=lease is not None,
        lease_state="" if lease is None else lease.state.value.upper(),
        lease_run_matches=bool(lease is not None and lease.run_id == observation.run_id),
        artifact_collection_id=None if artifact_collection is None else artifact_collection.collection_id,
        artifact_run_matches=bool(
            artifact_collection is not None
            and artifact_collection.run_id == observation.run_id
        ),
        artifact_lease_matches=bool(
            artifact_collection is not None
            and artifact_collection.lease_id == observation.sandbox_lease_ref
        ),
    )


@dataclass(frozen=True, slots=True)
class CloudM1TeardownReceipt:
    receipt_id: str
    plan_id: str
    plan_fingerprint: str
    run_id: str
    observation_id: str
    observed_at: datetime
    clean: bool
    evidence_sha256: str
    # Recorded, not decorative: a receipt states which lease/artifact evidence it
    # actually checked, so "clean" is auditable rather than a bare boolean.
    lease_state_verified: str
    artifact_collection_id: str | None
    verification_blockers: tuple[str, ...]

    @classmethod
    def from_observation(
        cls,
        *,
        receipt_id: str,
        plan: CloudM1ExecutionPlan,
        observation: TrustedTeardownObservation,
        lease_lookup: Any,
        artifact_collection: Any,
    ) -> "CloudM1TeardownReceipt":
        if not isinstance(plan, CloudM1ExecutionPlan):
            raise ContractError("plan must be CloudM1ExecutionPlan")
        if not isinstance(observation, TrustedTeardownObservation):
            raise ContractError("observation must be TrustedTeardownObservation")
        if observation.plan_id != plan.plan_id or observation.run_id != plan.run_id:
            raise ContractError("teardown observation does not belong to execution plan")

        # #2783: attestation alone can no longer produce a clean verdict. The
        # lease must be resolvable, belong to this run, and have left the active
        # state, and artifact finalization must come from the bounded collection
        # contract rather than a free boolean. Unverifiable evidence yields a
        # truthful non-clean receipt instead of an error, so a stuck teardown
        # stays recordable and diagnosable.
        verification = verify_teardown_evidence(
            observation=observation,
            lease_lookup=lease_lookup,
            artifact_collection=artifact_collection,
        )
        blockers = verification.blocking_reasons()
        clean = observation.clean and not blockers
        payload = observation.safe_dict()
        payload.update(
            {
                "lease_state_verified": verification.lease_state or "UNRESOLVED",
                "artifact_collection_id": verification.artifact_collection_id or "ABSENT",
                "verification_blockers": list(blockers),
            }
        )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return cls(
            receipt_id=_ref(receipt_id, "receipt_id"),
            plan_id=plan.plan_id,
            plan_fingerprint=plan.fingerprint,
            run_id=plan.run_id,
            observation_id=observation.observation_id,
            observed_at=observation.observed_at,
            clean=clean,
            evidence_sha256=hashlib.sha256(encoded).hexdigest(),
            lease_state_verified=verification.lease_state or "UNRESOLVED",
            artifact_collection_id=verification.artifact_collection_id,
            verification_blockers=blockers,
        )

    def __post_init__(self) -> None:
        for field_name in ("receipt_id", "plan_id", "run_id", "observation_id"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.plan_fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", self.plan_fingerprint):
            raise ContractError("plan_fingerprint must be SHA-256")
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if not isinstance(self.clean, bool):
            raise ContractError("clean must be boolean")
        if not isinstance(self.evidence_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.evidence_sha256):
            raise ContractError("evidence_sha256 must be SHA-256")
        # A receipt cannot assert clean without naming the evidence behind it.
        for field_name in ("lease_state_verified",):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Z_]{1,32}", value):
                raise ContractError(f"{field_name} must be a bounded reason token")
        if self.verification_blockers is None or not isinstance(self.verification_blockers, tuple):
            raise ContractError("verification_blockers must be a tuple")
        for reason in self.verification_blockers:
            if not isinstance(reason, str) or not re.fullmatch(r"[A-Z0-9_]{1,64}", reason):
                raise ContractError("verification blocker must be a bounded reason token")
        if self.clean and self.verification_blockers:
            raise ContractError("clean teardown receipt cannot carry a verification blocker")
        if self.clean and self.lease_state_verified not in LEASE_TERMINAL_STATE_TOKENS:
            raise ContractError("clean teardown receipt requires a terminal verified lease")
        if self.clean and not self.artifact_collection_id:
            raise ContractError("clean teardown receipt requires artifact collection evidence")

    def as_stage_receipt(self, *, event_id: str) -> CloudM1StageReceipt:
        return CloudM1StageReceipt(
            event_id=_ref(event_id, "event_id"),
            plan_id=self.plan_id,
            plan_fingerprint=self.plan_fingerprint,
            stage=CloudM1Stage.TEARDOWN,
            outcome=CloudStageOutcome.SUCCEEDED if self.clean else CloudStageOutcome.FAILED,
            observed_at=self.observed_at,
            evidence_ref=f"teardown:{self.receipt_id}:{self.evidence_sha256[:24]}",
            summary_code="teardown_clean" if self.clean else "teardown_incomplete",
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cloud-m1-teardown-receipt.v1",
            "receipt_id": self.receipt_id,
            "plan_id": self.plan_id,
            "plan_fingerprint": self.plan_fingerprint,
            "run_id": self.run_id,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "clean": self.clean,
            "evidence_sha256": self.evidence_sha256,
            "lease_state_verified": self.lease_state_verified,
            "artifact_collection_id": self.artifact_collection_id or "ABSENT",
            "verification_blockers": list(self.verification_blockers),
            "false_clean_teardown_supported": False,
            "raw_runtime_payload": False,
            "provider_endpoint": False,
            "credential_value": False,
        }


REAL_TEARDOWN_PROBE_CONFIGURED = False
FALSE_CLEAN_TEARDOWN_SUPPORTED = False
