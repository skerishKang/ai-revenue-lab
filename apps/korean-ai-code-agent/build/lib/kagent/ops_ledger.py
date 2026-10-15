from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import ContractError
from .ops_contracts import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalProjection,
    BusinessObjectKind,
    WorkflowEvidenceRecord,
)


@dataclass(frozen=True, slots=True)
class BusinessObjectEnvelope:
    kind: BusinessObjectKind
    object_id: str
    version: int
    workspace_id: str
    value: Any


class InMemoryOpsLedger:
    """Deterministic product-local ledger for tests and early vertical slices.

    This is not an accounting ledger and does not replace P01 evidence authority.
    It only keeps immutable/versioned Claw Ops product records and projections.
    """

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str, str, int], BusinessObjectEnvelope] = {}
        self._latest_versions: dict[tuple[str, str, str], int] = {}
        self._evidence: dict[str, WorkflowEvidenceRecord] = {}
        self._approvals: dict[str, ApprovalProjection] = {}

    @staticmethod
    def _object_key(
        workspace_id: str,
        kind: BusinessObjectKind,
        object_id: str,
        version: int,
    ) -> tuple[str, str, str, int]:
        return (workspace_id, kind.value, object_id, version)

    @staticmethod
    def _latest_key(
        workspace_id: str,
        kind: BusinessObjectKind,
        object_id: str,
    ) -> tuple[str, str, str]:
        return (workspace_id, kind.value, object_id)

    def append_object(self, envelope: BusinessObjectEnvelope) -> None:
        if not isinstance(envelope, BusinessObjectEnvelope):
            raise ContractError("envelope must be BusinessObjectEnvelope")
        if not isinstance(envelope.kind, BusinessObjectKind):
            raise ContractError("envelope.kind must be BusinessObjectKind")
        if not isinstance(envelope.version, int) or isinstance(envelope.version, bool) or envelope.version < 1:
            raise ContractError("envelope.version must be a positive integer")
        if not envelope.workspace_id or not envelope.object_id:
            raise ContractError("workspace_id and object_id are required")

        key = self._object_key(
            envelope.workspace_id,
            envelope.kind,
            envelope.object_id,
            envelope.version,
        )
        if key in self._objects:
            raise ContractError("business object version already exists")

        latest_key = self._latest_key(
            envelope.workspace_id,
            envelope.kind,
            envelope.object_id,
        )
        latest = self._latest_versions.get(latest_key)
        if latest is not None and envelope.version != latest + 1:
            raise ContractError("business object versions must be contiguous")
        if latest is None and envelope.version != 1:
            raise ContractError("first business object version must be 1")

        self._objects[key] = envelope
        self._latest_versions[latest_key] = envelope.version

    def get_object(
        self,
        *,
        workspace_id: str,
        kind: BusinessObjectKind,
        object_id: str,
        version: int,
    ) -> BusinessObjectEnvelope:
        key = self._object_key(workspace_id, kind, object_id, version)
        try:
            return self._objects[key]
        except KeyError as exc:
            raise ContractError("business object version not found") from exc

    def latest_object(
        self,
        *,
        workspace_id: str,
        kind: BusinessObjectKind,
        object_id: str,
    ) -> BusinessObjectEnvelope:
        latest_key = self._latest_key(workspace_id, kind, object_id)
        try:
            version = self._latest_versions[latest_key]
        except KeyError as exc:
            raise ContractError("business object not found") from exc
        return self.get_object(
            workspace_id=workspace_id,
            kind=kind,
            object_id=object_id,
            version=version,
        )

    def add_evidence(self, evidence: WorkflowEvidenceRecord) -> None:
        if not isinstance(evidence, WorkflowEvidenceRecord):
            raise ContractError("evidence must be WorkflowEvidenceRecord")
        if evidence.evidence_id in self._evidence:
            existing = self._evidence[evidence.evidence_id]
            if existing == evidence:
                return
            raise ContractError("evidence_id replay conflicts with existing evidence")
        self.get_object(
            workspace_id=evidence.workspace_id,
            kind=evidence.object_kind,
            object_id=evidence.object_id,
            version=evidence.object_version,
        )
        self._evidence[evidence.evidence_id] = evidence

    def evidence_for_object(
        self,
        *,
        workspace_id: str,
        kind: BusinessObjectKind,
        object_id: str,
        version: int,
    ) -> tuple[WorkflowEvidenceRecord, ...]:
        return tuple(
            item
            for item in self._evidence.values()
            if item.workspace_id == workspace_id
            and item.object_kind is kind
            and item.object_id == object_id
            and item.object_version == version
        )

    def add_approval_projection(self, approval: ApprovalProjection) -> None:
        if not isinstance(approval, ApprovalProjection):
            raise ContractError("approval must be ApprovalProjection")
        self.get_object(
            workspace_id=approval.workspace_id,
            kind=approval.target_kind,
            object_id=approval.target_id,
            version=approval.target_version,
        )
        existing = self._approvals.get(approval.approval_id)
        if existing is None:
            self._approvals[approval.approval_id] = approval
            return
        if existing == approval:
            return
        if existing.decision is not ApprovalDecision.PENDING:
            raise ContractError("decided approval projection is immutable")
        if approval.decision is ApprovalDecision.PENDING:
            raise ContractError("pending approval replay conflicts with existing projection")
        if (
            existing.workspace_id != approval.workspace_id
            or existing.action is not approval.action
            or existing.target_kind is not approval.target_kind
            or existing.target_id != approval.target_id
            or existing.target_version != approval.target_version
            or existing.action_fingerprint != approval.action_fingerprint
        ):
            raise ContractError("approval decision does not match the pending approval target")
        self._approvals[approval.approval_id] = approval

    def approval(self, approval_id: str) -> ApprovalProjection:
        try:
            return self._approvals[approval_id]
        except KeyError as exc:
            raise ContractError("approval projection not found") from exc

    def require_approved_action(
        self,
        *,
        approval_id: str,
        workspace_id: str,
        action: ApprovalAction,
        target_kind: BusinessObjectKind,
        target_id: str,
        target_version: int,
        action_fingerprint: str,
    ) -> ApprovalProjection:
        approval = self.approval(approval_id)
        if approval.decision is not ApprovalDecision.APPROVED:
            raise ContractError("approval is not approved")
        if approval.workspace_id != workspace_id:
            raise ContractError("approval workspace mismatch")
        if approval.action is not action:
            raise ContractError("approval action mismatch")
        if approval.target_kind is not target_kind:
            raise ContractError("approval target kind mismatch")
        if approval.target_id != target_id or approval.target_version != target_version:
            raise ContractError("approval target version mismatch")
        if approval.action_fingerprint != action_fingerprint:
            raise ContractError("approval action fingerprint mismatch")

        latest = self.latest_object(
            workspace_id=workspace_id,
            kind=target_kind,
            object_id=target_id,
        )
        if latest.version != target_version:
            raise ContractError("approval is stale because the target object has a newer version")
        return approval
