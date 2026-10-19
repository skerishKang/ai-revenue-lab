"""#3580 DriveWriteApprovalPort over the existing canonical P01 approval machinery.

``GoogleDriveArtifactUploadAdapter`` refuses to create a Drive file until its
injected ``DriveWriteApprovalPort`` returns ``True`` for the *exact* write
intent. No host implementation of that port existed, so the Drive WRITE path
could not be composed even with a grant.

This module is that implementation. It introduces **no** approval authority and
**no** approval schema — it is a Drive-specific validator/projection over the
existing canonical P01 evidence envelope, exactly as
``browser_control_lease_authority.BrowserControlAuthorityEvidence`` is for
``browser.control``:

```text
REUSED (canonical, unmodified)
  padiem_ai_core.agent_approval.ApprovalPause
  padiem_ai_core.agent_approval.VerifiedApprovalDecision
  padiem_ai_core.agent_approval.resolve_approval_pause
  padiem_ai_core.agent_approval.tool_invocation_digest
  padiem_ai_core.tool_runtime.ToolInvocation

NEW (this file)
  the canonical Drive-write argument map, and a validator that binds a pause
  to it and consumes the decision exactly once.
```

The pause/decision objects come from the injected trusted evidence port (in
production the existing P01/Control Plane evidence boundary). This module never
mints, stores or relaxes an approval.

```text
READ_APPROVAL_IS_NOT_WRITE_APPROVAL=True
CLIENT_CLAIM_IS_NOT_APPROVAL=True
NEW_APPROVAL_AUTHORITY=False
NEW_APPROVAL_SCHEMA=False
NEW_DURABLE_STORE=False
AUTO_RETRY=False
```

A ``drive.readonly`` approval (a READ pause: different tool, no
``drive.files.create`` in scope) can never satisfy this port, and #2010 keeps
the operational grant at READ, so the port stays inert in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from padiem_ai_core.agent_approval import (
    AgentApprovalError, ApprovalOutcome, ApprovalPause, ContinuationStatus,
    VerifiedApprovalDecision, resolve_approval_pause, tool_invocation_digest,
)
from padiem_ai_core.tool_runtime import ToolInvocation

from .artifact_lineage import LineageArtifactRef
from .connector_trust import ConnectorWriteIntent
from .contracts import ContractError
from .google_drive_artifact_upload import (
    DRIVE_UPLOAD_CAPABILITY, DRIVE_UPLOAD_TOOL,
)

DRIVE_WRITE_APPROVAL_CONTRACT_VERSION = "claw-drive-write-approval.v1"

#: The pause tool id the canonical P01 machinery must have paused on. Reused
#: from the existing write intent vocabulary; not a new tool name.
DRIVE_WRITE_TOOL_ID = DRIVE_UPLOAD_TOOL

#: Static contract markers for this validator.
READ_APPROVAL_IS_NOT_WRITE_APPROVAL = True
CLIENT_CLAIM_IS_NOT_APPROVAL = True
NEW_APPROVAL_AUTHORITY = False
NEW_APPROVAL_SCHEMA = False
NEW_DURABLE_STORE = False
AUTO_RETRY = False
PRODUCTION_APPROVAL_PORT_COMPOSED = False
RAW_APPROVAL_MATERIAL_IN_PROJECTION = False

#: The complete Drive-write argument surface the approval is bound to. It is
#: derived only from refs the adapter already validated — never from model text,
#: a browser body or a local path — and it is the single source of the digest a
#: trusted P01 host must reproduce when it pauses this tool.
DRIVE_WRITE_APPROVAL_ARGUMENT_FIELDS = (
    "connector_id", "binding_ref", "actor_ref", "tool_name", "workspace_ref",
    "run_ref", "artifact_id", "artifact_sha256", "folder_ref",
    "payload_fingerprint", "capability", "overwrite_original", "local_pc_access",
)


class DriveWriteApprovalError(ContractError):
    """Fail-closed validator error; never carries approval material or a token."""


def drive_write_approval_arguments(
    *, intent: ConnectorWriteIntent, artifact_ref: LineageArtifactRef,
    workspace_ref: str, run_ref: str,
) -> dict[str, Any]:
    """The exact, bounded Drive-write argument map an approval must bind.

    Deterministic and free of secrets, provider ids and local paths, so the
    trusted P01 host can reproduce it byte for byte before pausing.
    """
    if not isinstance(intent, ConnectorWriteIntent):
        raise DriveWriteApprovalError("canonical connector write intent required")
    if not isinstance(artifact_ref, LineageArtifactRef):
        raise DriveWriteApprovalError("canonical artifact reference required")
    for name, value in (("workspace_ref", workspace_ref), ("run_ref", run_ref)):
        if not isinstance(value, str) or not value:
            raise DriveWriteApprovalError(f"trusted {name} required")
    return {
        "connector_id": intent.connector_id,
        "binding_ref": intent.binding_ref,
        "actor_ref": intent.actor_ref,
        "tool_name": intent.tool_name,
        "workspace_ref": workspace_ref,
        "run_ref": run_ref,
        "artifact_id": artifact_ref.artifact_id,
        "artifact_sha256": artifact_ref.integrity_ref,
        "folder_ref": intent.target_ref,
        "payload_fingerprint": intent.payload_fingerprint,
        "capability": DRIVE_UPLOAD_CAPABILITY,
        "overwrite_original": False,
        "local_pc_access": False,
    }


def drive_write_tool_invocation(
    *, intent: ConnectorWriteIntent, artifact_ref: LineageArtifactRef,
    workspace_ref: str, run_ref: str,
) -> ToolInvocation:
    """The canonical invocation the P01 pause must be bound to."""
    return ToolInvocation(
        tool_id=DRIVE_WRITE_TOOL_ID,
        arguments=drive_write_approval_arguments(
            intent=intent, artifact_ref=artifact_ref,
            workspace_ref=workspace_ref, run_ref=run_ref,
        ),
    )


def drive_write_approval_fingerprint(
    *, intent: ConnectorWriteIntent, artifact_ref: LineageArtifactRef,
    workspace_ref: str, run_ref: str,
) -> str:
    """Reuse the canonical invocation digest; do not invent a second hash."""
    return tool_invocation_digest(drive_write_tool_invocation(
        intent=intent, artifact_ref=artifact_ref,
        workspace_ref=workspace_ref, run_ref=run_ref,
    ))


@dataclass(frozen=True, slots=True)
class DriveWriteApprovalEvidence:
    """Authenticated canonical P01 evidence for one exact Drive write.

    A Drive-specific *validator/projection* over the existing P01 evidence
    envelope: the pause and decision come from the canonical P01 route and the
    correlation copies are taken from whatever the canonical evidence carries,
    never minted here.
    """

    evidence_ref: str
    request_fingerprint: str
    approval_pause: ApprovalPause
    approval_decision: VerifiedApprovalDecision
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_ref, str) or not self.evidence_ref:
            raise DriveWriteApprovalError("evidence_ref must be non-empty text")
        if (
            not isinstance(self.request_fingerprint, str)
            or len(self.request_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in self.request_fingerprint)
        ):
            raise DriveWriteApprovalError("request_fingerprint must be a SHA-256 digest")
        if not isinstance(self.approval_pause, ApprovalPause):
            raise DriveWriteApprovalError("approval_pause must be canonical ApprovalPause")
        if not isinstance(self.approval_decision, VerifiedApprovalDecision):
            raise DriveWriteApprovalError(
                "approval_decision must be canonical VerifiedApprovalDecision"
            )
        if self.approval_pause.tool_id != DRIVE_WRITE_TOOL_ID:
            raise DriveWriteApprovalError(
                "Drive write evidence must target the canonical Drive upload tool"
            )
        if self.approval_decision.pause_id != self.approval_pause.pause_id:
            raise DriveWriteApprovalError(
                "approval decision does not belong to the supplied pause"
            )
        if self.approval_decision.evidence_ref != self.evidence_ref:
            raise DriveWriteApprovalError(
                "approval decision evidence_ref does not match the evidence"
            )
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
            raise DriveWriteApprovalError("evidence expiry must be timezone-aware")
        expires_at = self.expires_at.astimezone(timezone.utc)
        object.__setattr__(self, "expires_at", expires_at)
        if expires_at <= self.approval_decision.decided_at.astimezone(timezone.utc):
            raise DriveWriteApprovalError("evidence expiry must be after the decision")
        if expires_at > self.approval_pause.expires_at.astimezone(timezone.utc):
            raise DriveWriteApprovalError(
                "Drive write evidence cannot outlive the P01 approval pause"
            )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": DRIVE_WRITE_APPROVAL_CONTRACT_VERSION,
            "evidence_ref": self.evidence_ref,
            "request_fingerprint": self.request_fingerprint,
            "pause_id": self.approval_pause.pause_id,
            "decision_id": self.approval_decision.decision_id,
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "raw_approval_material": False,
            "raw_access_token": False,
            "raw_refresh_token": False,
            "client_approval_authority": False,
        }


class DriveWriteApprovalEvidencePort(Protocol):
    """Trusted boundary yielding authenticated evidence for a fingerprint."""

    def resolve_drive_write_approval(
        self, *, request_fingerprint: str,
    ) -> DriveWriteApprovalEvidence | None: ...


class UnconfiguredDriveWriteApprovalEvidencePort:
    """Fails closed when no trusted evidence source is wired."""

    def resolve_drive_write_approval(
        self, *, request_fingerprint: str,
    ) -> DriveWriteApprovalEvidence | None:
        return None


class InMemoryDriveWriteApprovalConsumption:
    """One-shot decision consumption for this process.

    Not a durable store: cross-worker replay protection belongs to the
    separately authorized platform store, and no such store is created here.
    """

    def __init__(self) -> None:
        self._consumed: set[str] = set()

    def consumed_decision_ids(self) -> frozenset[str]:
        return frozenset(self._consumed)

    def consume(self, decision_id: str) -> bool:
        """Return True exactly once per decision id."""
        if not isinstance(decision_id, str) or not decision_id:
            return False
        if decision_id in self._consumed:
            return False
        self._consumed.add(decision_id)
        return True


class AuthorizedDriveWriteApprovalPort:
    """``DriveWriteApprovalPort`` over the existing canonical P01 evidence.

    Every step fails closed and returns ``False``; the caller cannot supply a
    boolean approval, and no approval material is reconstructed here.
    """

    def __init__(
        self, *,
        evidence_port: DriveWriteApprovalEvidencePort | None = None,
        consumption: InMemoryDriveWriteApprovalConsumption | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if evidence_port is not None and not callable(
            getattr(evidence_port, "resolve_drive_write_approval", None)
        ):
            raise DriveWriteApprovalError(
                "evidence port must resolve Drive write approval evidence"
            )
        if consumption is not None and not callable(
            getattr(consumption, "consume", None)
        ):
            raise DriveWriteApprovalError("consumption registry must consume decisions")
        self._evidence_port = (
            evidence_port if evidence_port is not None
            else UnconfiguredDriveWriteApprovalEvidencePort()
        )
        self._consumption = (
            consumption if consumption is not None
            else InMemoryDriveWriteApprovalConsumption()
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def verify_write_approval(
        self, *, intent: ConnectorWriteIntent, artifact_ref: LineageArtifactRef,
        workspace_ref: str, run_ref: str,
    ) -> bool:
        """True only for a live, exact, still-approved, unused WRITE decision."""
        try:
            return self._verify(
                intent=intent, artifact_ref=artifact_ref,
                workspace_ref=workspace_ref, run_ref=run_ref,
            )
        except Exception:
            # Approval material, provider text and exceptions must never reach
            # the upload adapter's caller. Fail closed.
            return False

    def _verify(
        self, *, intent: ConnectorWriteIntent, artifact_ref: LineageArtifactRef,
        workspace_ref: str, run_ref: str,
    ) -> bool:
        # 1. Only a Google Drive *create* intent can be approved here. A READ
        #    intent, an overwrite/version-pinned intent and a foreign connector
        #    are refused before any evidence lookup.
        if (
            not isinstance(intent, ConnectorWriteIntent)
            or intent.connector_id != "google-drive"
            or intent.tool_name != DRIVE_WRITE_TOOL_ID
            or intent.expected_version_ref is not None
        ):
            return False

        fingerprint = drive_write_approval_fingerprint(
            intent=intent, artifact_ref=artifact_ref,
            workspace_ref=workspace_ref, run_ref=run_ref,
        )

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            return False
        now = now.astimezone(timezone.utc)

        # 2. Trusted evidence must exist for this exact request fingerprint.
        evidence = self._evidence_port.resolve_drive_write_approval(
            request_fingerprint=fingerprint
        )
        if not isinstance(evidence, DriveWriteApprovalEvidence):
            return False
        if evidence.request_fingerprint != fingerprint:
            return False
        if evidence.expires_at <= now:
            return False

        pause, decision = evidence.approval_pause, evidence.approval_decision
        # 3. The pause must bind this exact invocation and run, and the scope
        #    must carry the WRITE capability — a READ approval never qualifies.
        if (
            decision.outcome is not ApprovalOutcome.APPROVED
            or pause.tool_id != DRIVE_WRITE_TOOL_ID
            or pause.run_id != run_ref
            or pause.invocation_sha256 != fingerprint
            or DRIVE_UPLOAD_CAPABILITY not in set(pause.approval_scope)
        ):
            return False

        # 4. Canonical lifecycle: approved, unexpired, and not already consumed.
        try:
            state = resolve_approval_pause(
                pause, decision, now=now,
                consumed_decision_ids=self._consumption.consumed_decision_ids(),
            )
        except AgentApprovalError:
            return False
        if state.status is not ContinuationStatus.RESUMABLE:
            return False

        # 5. One-shot: the same decision can never authorize a second upload.
        return self._consumption.consume(decision.decision_id) is True


__all__ = [
    "AuthorizedDriveWriteApprovalPort",
    "CLIENT_CLAIM_IS_NOT_APPROVAL",
    "DRIVE_WRITE_APPROVAL_ARGUMENT_FIELDS",
    "DRIVE_WRITE_APPROVAL_CONTRACT_VERSION",
    "DRIVE_WRITE_TOOL_ID",
    "DriveWriteApprovalError",
    "DriveWriteApprovalEvidence",
    "DriveWriteApprovalEvidencePort",
    "InMemoryDriveWriteApprovalConsumption",
    "NEW_APPROVAL_AUTHORITY",
    "NEW_APPROVAL_SCHEMA",
    "NEW_DURABLE_STORE",
    "PRODUCTION_APPROVAL_PORT_COMPOSED",
    "READ_APPROVAL_IS_NOT_WRITE_APPROVAL",
    "UnconfiguredDriveWriteApprovalEvidencePort",
    "drive_write_approval_arguments",
    "drive_write_approval_fingerprint",
    "drive_write_tool_invocation",
]
