"""#3580: exact Engine-verified Office READ receipt -> Resident P01 file plan.

This is a *trusted host injected* source, never a browser/command JSON parser.
The authentication and transport layer supplies the owner/session-scoped
redemption. The existing Windows P01/local permission port still authorizes
every READ and refuses expired or mismatched evidence. No direct IO here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement, ContinuationStatus,
    VerifiedApprovalDecision, resolve_approval_pause, tool_invocation_digest,
)

from .contracts import ContractError
from .local_agent_control_plane_admission import ControlPlaneAdmittedExecutionReceipt
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope
from .local_agent_permissions import LocalPermissionRequest
from .trusted_p01_office_file_plan import TrustedP01OfficeFilePlan
from .windows_local_executor import WindowsExecutionTermination
from .windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, WindowsFileAuthorityEvidence,
    file_request_fingerprint, windows_file_tool_invocation,
)

_MAX_AGE = timedelta(minutes=5)
_REQUIRED_ARGS = frozenset({
    "action_id", "run_id", "device_id", "root_ref",
    "operation", "path_relative", "requested_at", "request_fingerprint",
    "content_bytes", "content_sha256", "directory_enumeration",
    "recursive_delete", "admin_elevation",
})


class TrustedOfficeReadEvidenceRedeemer(Protocol):
    """Private authenticated host mechanism, not an arbitrary HTTP URL."""

    def redeem_for_trusted_command(self, trusted_binding: Any) -> Any: ...


class VerifiedEngineOfficeReadPlanSource:
    """The missing receipt-to-canonical-Resident plan conversion boundary.

    The trusted binding resolver must correlate authenticated owner+session with
    the *already admitted* Broker command. The redeemer must be authenticated,
    durable, one-shot and return the exact canonical Engine evidence. Neither
    value may be derived from the browser or an untrusted resident message.
    """

    def __init__(
        self, *,
        trusted_binding_resolver: Callable[..., Any],
        evidence_redeemer: TrustedOfficeReadEvidenceRedeemer,
        local_policy_ref: str,
    ) -> None:
        if (not callable(trusted_binding_resolver)
                or not callable(getattr(evidence_redeemer, "redeem_for_trusted_command", None))
                or not isinstance(local_policy_ref, str)
                or not local_policy_ref or len(local_policy_ref) > 128):
            raise ContractError("private authenticated P01 Office authority required")
        self._resolver = trusted_binding_resolver
        self._redeemer = evidence_redeemer
        self._policy_ref = local_policy_ref

    def approved_plan(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> TrustedP01OfficeFilePlan | None:
        if (not isinstance(binding, DeviceBinding)
                or not isinstance(command, DeviceCommandEnvelope)
                or not isinstance(receipt, ControlPlaneAdmittedExecutionReceipt)):
            raise ContractError("canonical Broker admitted command required")
        ack = receipt.execution
        if (ack.command_id != command.command_id
                or ack.run_id != command.run_id
                or ack.binding_ref != binding.binding_ref
                or ack.tool_request_ref != command.tool_request_ref
                or ack.revision_ref != command.revision_ref
                or ack.sequence != command.sequence
                or ack.termination is not WindowsExecutionTermination.EXITED
                or ack.exit_code != 0):
            raise ContractError("exact successful Broker ACK required")

        scoped = self._resolver(binding=binding, command=command, receipt=receipt)
        if scoped is None:
            return None
        # Reject uncorrelated host binding BEFORE consuming a one-shot receipt.
        if (getattr(scoped, "binding_ref", None) != binding.binding_ref
                or getattr(scoped, "command_id", None) != command.command_id
                or getattr(scoped, "tool_request_ref", None) != command.tool_request_ref
                or getattr(scoped, "run_id", None) != command.run_id
                or getattr(scoped, "request_id", None) != ack.request_id
                or getattr(scoped, "revision_ref", None) != command.revision_ref
                or getattr(scoped, "command_fingerprint", None) != ack.request_fingerprint
                or getattr(scoped, "sequence", None) != command.sequence
                or getattr(scoped, "device_id", None) != binding.device_id):
            raise ContractError("authenticated Office command binding mismatch")

        redeemed = self._redeemer.redeem_for_trusted_command(scoped)
        if redeemed is None:
            return None
        if getattr(redeemed, "binding", None) != scoped:
            raise ContractError("private Office evidence foreign owner/session/command")
        verified = getattr(redeemed, "receipt", None)
        pause = getattr(verified, "pause", None)
        decision = getattr(verified, "verified_decision", None)
        if (not isinstance(pause, ApprovalPause)
                or not isinstance(decision, VerifiedApprovalDecision)
                or pause.run_id != command.run_id
                or pause.tool_id != "local.filesystem.read"
                or pause.requirement is not ApprovalRequirement.USER_CONFIRMATION
                or pause.approval_scope != ("filesystem.read",)
                or decision.pause_id != pause.pause_id
                or decision.outcome is not ApprovalOutcome.APPROVED):
            raise ContractError("canonical first-party P01 READ approval required")
        try:
            args = dict(verified.exact_tool_arguments)
            if (len(args) != len(verified.exact_tool_arguments)
                    or set(args) != _REQUIRED_ARGS
                    or args["run_id"] != command.run_id
                    or args["device_id"] != binding.device_id
                    or args["root_ref"] != scoped.root_ref
                    or args["operation"] != "read"
                    or args["content_bytes"] != 0
                    or args["content_sha256"] is not None
                    or any(args[k] is not False for k in (
                        "directory_enumeration", "recursive_delete", "admin_elevation"
                    ))):
                raise ValueError("noncanonical selected Office file READ")
            req = LocalFileRequest(
                action_id=args["action_id"], run_id=args["run_id"],
                device_id=args["device_id"], root_ref=args["root_ref"],
                operation=LocalFileOperation.READ, path_relative=args["path_relative"],
                requested_at=datetime.fromisoformat(args["requested_at"].replace("Z", "+00:00")),
            )
            if not req.path_relative.lower().endswith(".xlsx"):
                raise ValueError("only exact XLSX selected file can be read")
            fingerprint = file_request_fingerprint(req)
            if (fingerprint != args["request_fingerprint"]
                    or fingerprint != scoped.request_fingerprint
                    or pause.invocation_sha256 != tool_invocation_digest(
                        windows_file_tool_invocation(req)
                    )):
                raise ValueError("Engine digest / canonical Windows request mismatch")
        except (TypeError, KeyError, AttributeError, ValueError) as exc:
            raise ContractError("Engine evidence does not bind canonical Windows READ") from exc

        now = receipt.acknowledged_at
        expires_at = min(
            pause.expires_at, decision.decided_at + _MAX_AGE, now + _MAX_AGE,
        )
        if (now < decision.decided_at - timedelta(seconds=30)
                or expires_at <= now
                or resolve_approval_pause(pause, decision, now=now).status
                is not ContinuationStatus.RESUMABLE):
            raise ContractError("verified Office approval expired or invalid")
        authority = WindowsFileAuthorityEvidence(
            evidence_ref=decision.evidence_ref,
            request_fingerprint=fingerprint,
            permission_request=LocalPermissionRequest(
                action_id=req.action_id, run_id=req.run_id,
                device_id=req.device_id, capability=req.capability,
                target_ref=fingerprint, root_ref=req.root_ref,
            ),
            approval_pause=pause,
            approval_decision=decision,
            local_policy_ref=self._policy_ref,
            expires_at=expires_at,
        )
        return TrustedP01OfficeFilePlan(
            binding_ref=binding.binding_ref,
            command_id=command.command_id,
            tool_request_ref=command.tool_request_ref,
            run_id=command.run_id,
            request_id=ack.request_id,
            revision_ref=command.revision_ref,
            command_fingerprint=ack.request_fingerprint,
            sequence=command.sequence,
            file_request=req, file_evidence=authority,
        )


VERIFIED_RECEIPT_PLAN_MINTS_APPROVAL = False
VERIFIED_RECEIPT_PLAN_READS_FILES = False
