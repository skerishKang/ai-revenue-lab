"""#3580: exact-command P01 approved Office file plan → existing one-shot file authority.

This module does not issue approvals or grant filesystem access. A trusted host
must supply BOTH the immutable canonical file READ request and its pre-existing
P01 approval + local permission evidence. The existing
P01LocalPermissionWindowsFileAuthorizationPort remains the ONLY READ authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from threading import Lock
from typing import Protocol

from .contracts import ContractError
from .local_agent_control_plane_admission import ControlPlaneAdmittedExecutionReceipt
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope
from .windows_local_executor import WindowsExecutionTermination
from .windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, WindowsFileAuthorityEvidence,
    file_request_fingerprint,
)

MAX_PREAPPROVED_OFFICE_PLANS = 32
_MAX_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class TrustedP01OfficeFilePlan:
    """Attested *inputs* from the existing P01 host, never a new approval."""

    binding_ref: str
    command_id: str
    tool_request_ref: str
    run_id: str
    request_id: str
    revision_ref: str
    command_fingerprint: str
    sequence: int
    file_request: LocalFileRequest
    file_evidence: WindowsFileAuthorityEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.file_request, LocalFileRequest):
            raise ContractError("canonical P01 Office file request required")
        if not isinstance(self.file_evidence, WindowsFileAuthorityEvidence):
            raise ContractError("canonical P01 Office approval evidence required")
        if (self.file_request.operation is not LocalFileOperation.READ
                or not self.file_request.path_relative.lower().endswith(".xlsx")
                or self.file_request.run_id != self.run_id
                or self.file_evidence.request_fingerprint != file_request_fingerprint(self.file_request)
                or len(self.command_fingerprint) != 64
                or isinstance(self.sequence, bool) or not isinstance(self.sequence, int)
                or self.sequence <= 0):
            raise ContractError("Office file plan not bound to exact authorized READ")


class TrustedP01OfficePlanSource(Protocol):
    """Injected local P01 authority material; no JSON/env/browser fallback.

    The source must return an already verified canonical plan for exactly the
    acknowledged Broker command, or None. It must not mint user consent.
    """

    def approved_plan(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> TrustedP01OfficeFilePlan | None: ...


class TrustedP01OfficeFilePlanBridge:
    """One-shot host adapter: both request plan and canonical evidence lookup.

    The latter is consumed by the existing Windows file authorization port,
    which independently re-evaluates local policy + P01 pause/decision. Nothing
    bypasses or replaces that port.
    """

    def __init__(self, *, source: TrustedP01OfficePlanSource) -> None:
        if not callable(getattr(source, "approved_plan", None)):
            raise ContractError("trusted P01 Office plan source required")
        self._source = source
        self._lock = Lock()
        self._pending: dict[str, WindowsFileAuthorityEvidence] = {}
        self._consumed_commands: set[tuple[str, str]] = set()

    def request_for_completed_command(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> LocalFileRequest | None:
        if (not isinstance(binding, DeviceBinding)
                or not isinstance(command, DeviceCommandEnvelope)
                or not isinstance(receipt, ControlPlaneAdmittedExecutionReceipt)):
            raise ContractError("canonical P01 command required")
        fact = receipt.execution
        if (fact.command_id != command.command_id
                or fact.run_id != command.run_id
                or fact.binding_ref != binding.binding_ref
                or fact.tool_request_ref != command.tool_request_ref
                or fact.revision_ref != command.revision_ref
                or fact.sequence != command.sequence
                or fact.termination is not WindowsExecutionTermination.EXITED
                or fact.exit_code != 0):
            raise ContractError("successful exact Broker ACK required before Office READ")
        key = (binding.binding_ref, command.command_id)
        with self._lock:
            if key in self._consumed_commands:
                raise ContractError("Office command file plan already consumed")
            # Do not hold the lock around provider callbacks (may run I/O).
            self._consumed_commands.add(key)
        plan = self._source.approved_plan(
            binding=binding, command=command, receipt=receipt,
        )
        if plan is None:
            return None
        if not isinstance(plan, TrustedP01OfficeFilePlan):
            raise ContractError("Office plan source returned invalid authority material")
        request, evidence = plan.file_request, plan.file_evidence
        now = receipt.acknowledged_at
        if (plan.binding_ref != binding.binding_ref
                or plan.command_id != command.command_id
                or plan.tool_request_ref != command.tool_request_ref
                or plan.run_id != command.run_id
                or plan.request_id != fact.request_id
                or plan.revision_ref != command.revision_ref
                or plan.command_fingerprint != fact.request_fingerprint
                or plan.sequence != command.sequence
                or request.device_id != binding.device_id
                or request.run_id != command.run_id
                or evidence.expires_at <= now - _MAX_CLOCK_SKEW
                or evidence.approval_pause.run_id != command.run_id
                or evidence.approval_decision.pause_id != evidence.approval_pause.pause_id
                or request.requested_at > now + _MAX_CLOCK_SKEW):
            raise ContractError("Office P01 plan/approval correlation invalid")
        fingerprint = file_request_fingerprint(request)
        with self._lock:
            if len(self._pending) >= MAX_PREAPPROVED_OFFICE_PLANS or fingerprint in self._pending:
                raise ContractError("Office P01 evidence queue full/conflicting")
            self._pending[fingerprint] = evidence
        return request

    def resolve(self, request_fingerprint: str) -> WindowsFileAuthorityEvidence:
        if type(request_fingerprint) is not str or len(request_fingerprint) != 64:
            raise ContractError("exact file request SHA-256 required")
        with self._lock:
            evidence = self._pending.pop(request_fingerprint, None)
        if evidence is None:
            raise ContractError("Office READ requires unconsumed P01 evidence")
        return evidence

    def safe_dict(self) -> dict:
        with self._lock:
            return {
                "contract_version": "claw-trusted-p01-office-file-plan-bridge.v1",
                "pending_evidence_count": len(self._pending),
                "approval_authority_created": False,
                "device_credential_stored": False,
                "raw_file_bytes_stored": False,
                "browser_file_plan_accepted": False,
                "one_shot": True,
            }
