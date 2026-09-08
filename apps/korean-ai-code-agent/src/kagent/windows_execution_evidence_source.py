from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Protocol

from padiem_ai_core.agent_approval import ApprovalPause, VerifiedApprovalDecision

from .contracts import ContractError
from .local_agent_permissions import LocalPermissionRequest
from .windows_execution_authorization import (
    WINDOWS_EXECUTION_TOOL_ID,
    WindowsExecutionAuthorityEvidence,
    WindowsExecutionAuthorityEvidencePort,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _digest(value: str, field_name: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TrustedP01WindowsExecutionEvidenceEnvelope:
    """Already-authenticated P01 evidence returned by a trusted client boundary.

    This type does not authenticate a user or mint approval. It only carries the
    canonical Core approval objects and the local-policy evidence required by the
    existing Windows authorization adapter. Raw argv, credentials, browser
    session material and approval UI payloads are intentionally absent.
    """

    evidence_ref: str
    request_fingerprint: str
    approval_pause: ApprovalPause
    approval_decision: VerifiedApprovalDecision
    permission_requests: tuple[LocalPermissionRequest, ...]
    local_policy_ref: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(
            self,
            "request_fingerprint",
            _digest(self.request_fingerprint, "request_fingerprint"),
        )
        object.__setattr__(self, "local_policy_ref", _ref(self.local_policy_ref, "local_policy_ref"))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))

        if not isinstance(self.approval_pause, ApprovalPause):
            raise ContractError("approval_pause must be canonical ApprovalPause")
        if not isinstance(self.approval_decision, VerifiedApprovalDecision):
            raise ContractError("approval_decision must be canonical VerifiedApprovalDecision")
        if self.approval_pause.tool_id != WINDOWS_EXECUTION_TOOL_ID:
            raise ContractError("trusted Windows evidence must target local.process.execute")
        if self.approval_decision.pause_id != self.approval_pause.pause_id:
            raise ContractError("approval decision does not belong to the supplied pause")
        if self.approval_decision.evidence_ref != self.evidence_ref:
            raise ContractError("approval decision evidence_ref does not match the trusted envelope")

        if not isinstance(self.permission_requests, tuple) or not self.permission_requests:
            raise ContractError("permission_requests must be a non-empty tuple")
        if not all(isinstance(item, LocalPermissionRequest) for item in self.permission_requests):
            raise ContractError("permission_requests must contain LocalPermissionRequest values")
        capabilities = [item.capability for item in self.permission_requests]
        if len(capabilities) != len(set(capabilities)):
            raise ContractError("permission evidence must contain each capability exactly once")
        for item in self.permission_requests:
            if item.run_id != self.approval_pause.run_id:
                raise ContractError("permission evidence run_id does not match the P01 approval pause")
            if item.target_ref != self.request_fingerprint:
                raise ContractError("permission evidence is not bound to the exact command fingerprint")

        decided_at = _aware(self.approval_decision.decided_at, "approval_decision.decided_at")
        pause_expires_at = _aware(self.approval_pause.expires_at, "approval_pause.expires_at")
        if self.expires_at <= decided_at:
            raise ContractError("trusted evidence expiry must be after the approval decision")
        if self.expires_at > pause_expires_at:
            raise ContractError("trusted evidence cannot outlive the canonical P01 approval pause")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-trusted-p01-windows-evidence.v1",
            "evidence_ref": self.evidence_ref,
            "request_fingerprint": self.request_fingerprint,
            "pause_id": self.approval_pause.pause_id,
            "decision_id": self.approval_decision.decision_id,
            "authority_ref": self.approval_decision.authority_ref,
            "local_policy_ref": self.local_policy_ref,
            "permission_capabilities": sorted(item.capability.value for item in self.permission_requests),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "raw_argv": False,
            "raw_credential": False,
            "actor_session_payload": False,
            "approval_ui_payload": False,
            "client_approval_authority": False,
        }


class TrustedP01WindowsExecutionEvidenceClient(Protocol):
    """Trusted product/control-plane boundary; authentication lives outside B54."""

    def resolve(self, request_fingerprint: str) -> TrustedP01WindowsExecutionEvidenceEnvelope:
        ...


class UnconfiguredTrustedP01WindowsExecutionEvidenceClient:
    def resolve(self, request_fingerprint: str) -> TrustedP01WindowsExecutionEvidenceEnvelope:
        _digest(request_fingerprint, "request_fingerprint")
        raise ContractError("trusted P01 Windows execution evidence client is not configured")


class DeterministicTrustedP01WindowsExecutionEvidenceClient:
    """Network-free trusted-client double for conformance tests only."""

    def __init__(self, evidence: tuple[TrustedP01WindowsExecutionEvidenceEnvelope, ...]) -> None:
        if not isinstance(evidence, tuple) or not evidence:
            raise ContractError("deterministic trusted evidence client requires evidence")
        if not all(isinstance(item, TrustedP01WindowsExecutionEvidenceEnvelope) for item in evidence):
            raise ContractError("deterministic trusted evidence client contains invalid evidence")
        by_fingerprint = {item.request_fingerprint: item for item in evidence}
        if len(by_fingerprint) != len(evidence):
            raise ContractError("deterministic trusted evidence fingerprints must be unique")
        self._evidence = by_fingerprint
        self.calls: list[str] = []

    def resolve(self, request_fingerprint: str) -> TrustedP01WindowsExecutionEvidenceEnvelope:
        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        self.calls.append(fingerprint)
        try:
            return self._evidence[fingerprint]
        except KeyError as exc:
            raise ContractError("trusted P01 evidence does not exist for this command fingerprint") from exc


class TrustedP01WindowsExecutionAuthorityEvidencePort(WindowsExecutionAuthorityEvidencePort):
    """Convert trusted P01 evidence into the existing Windows authorization input.

    The adapter pins the expected P01 authority and exact command fingerprint.
    It does not approve, deny, refresh, store or consume approval decisions; the
    existing P01LocalPermissionWindowsExecutionAuthorizationPort remains the
    canonical final validator and single-use execution-grant issuer.
    """

    def __init__(
        self,
        *,
        expected_authority_ref: str,
        client: TrustedP01WindowsExecutionEvidenceClient | None = None,
    ) -> None:
        self._expected_authority_ref = _ref(expected_authority_ref, "expected_authority_ref")
        self._client = client or UnconfiguredTrustedP01WindowsExecutionEvidenceClient()

    def resolve(self, request_fingerprint: str) -> WindowsExecutionAuthorityEvidence:
        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        envelope = self._client.resolve(fingerprint)
        if not isinstance(envelope, TrustedP01WindowsExecutionEvidenceEnvelope):
            raise ContractError("trusted P01 evidence client returned an invalid envelope")
        if envelope.request_fingerprint != fingerprint:
            raise ContractError("trusted P01 evidence fingerprint mismatch")
        if envelope.approval_decision.authority_ref != self._expected_authority_ref:
            raise ContractError("trusted P01 approval authority mismatch")

        return WindowsExecutionAuthorityEvidence(
            evidence_ref=envelope.evidence_ref,
            request_fingerprint=envelope.request_fingerprint,
            permission_requests=envelope.permission_requests,
            approval_pause=envelope.approval_pause,
            approval_decision=envelope.approval_decision,
            local_policy_ref=envelope.local_policy_ref,
            expires_at=envelope.expires_at,
        )


TRUSTED_P01_WINDOWS_EVIDENCE_ADAPTER_IMPLEMENTED = True
P01_AUTHORITY_PINNED = True
EXACT_FINGERPRINT_LOOKUP = True
CLIENT_APPROVAL_AUTHORITY = False
P01_POLICY_DUPLICATED = False
RAW_ARGV_IN_EVIDENCE_ENVELOPE = False
RAW_CREDENTIAL_IN_EVIDENCE_ENVELOPE = False
REAL_P01_REMOTE_EVIDENCE_CLIENT_CONFIGURED = False
REAL_REMOTE_BROKER_CONFIGURED = False
PRODUCTION_READY = False
