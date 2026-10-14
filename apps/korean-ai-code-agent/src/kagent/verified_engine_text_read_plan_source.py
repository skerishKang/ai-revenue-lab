"""#4139: exact Engine-verified TXT READ evidence -> Resident P01 verified-text plan.

Admitted (pre-ACK) variant of VerifiedEngineOfficeReadPlanSource. It never waits
for a completed execution acknowledgement; the admitted correlation supplied by
the canonical command is sufficient input authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement, ContinuationStatus,
    VerifiedApprovalDecision, resolve_approval_pause, tool_invocation_digest,
)

from .contracts import ContractError
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope
from .local_resident_verified_text_delivery import (
    AdmittedTextReadContext, TrustedP01VerifiedTextFilePlan,
)
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


class TrustedTextReadEvidenceRedeemer(Protocol):
    def redeem_for_trusted_command(self, trusted_binding: Any) -> Any: ...


class VerifiedEngineTextReadPlanSource:
    def __init__(self, *, trusted_binding_resolver: Callable[..., Any],
                 evidence_redeemer: TrustedTextReadEvidenceRedeemer,
                 local_policy_ref: str) -> None:
        if (not callable(trusted_binding_resolver)
                or not callable(getattr(evidence_redeemer, "redeem_for_trusted_command", None))
                or not isinstance(local_policy_ref, str)
                or not local_policy_ref or len(local_policy_ref) > 128):
            raise ContractError("private authenticated P01 text authority required")
        self._resolver = trusted_binding_resolver
        self._redeemer = evidence_redeemer
        self._policy_ref = local_policy_ref

    def approved_plan_for_admitted_command(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        admitted: AdmittedTextReadContext,
    ) -> TrustedP01VerifiedTextFilePlan | None:
        if (not isinstance(binding, DeviceBinding)
                or not isinstance(command, DeviceCommandEnvelope)
                or not isinstance(admitted, AdmittedTextReadContext)):
            raise ContractError("canonical admitted Broker command required")
        if command.binding_ref != binding.binding_ref:
            raise ContractError("canonical admitted P01 command required")

        scoped = self._resolver(binding=binding, command=command, admitted=admitted)
        if scoped is None:
            return None
        if (getattr(scoped, "binding_ref", None) != binding.binding_ref
                or getattr(scoped, "command_id", None) != command.command_id
                or getattr(scoped, "tool_request_ref", None) != command.tool_request_ref
                or getattr(scoped, "run_id", None) != command.run_id
                or getattr(scoped, "request_id", None) != admitted.request_id
                or getattr(scoped, "revision_ref", None) != command.revision_ref
                or getattr(scoped, "command_fingerprint", None) != admitted.command_fingerprint
                or getattr(scoped, "sequence", None) != command.sequence
                or getattr(scoped, "device_id", None) != binding.device_id):
            raise ContractError("authenticated text command binding mismatch")

        redeemed = self._redeemer.redeem_for_trusted_command(scoped)
        if redeemed is None:
            return None
        if getattr(redeemed, "binding", None) != scoped:
            raise ContractError("private text evidence foreign owner/session/command")

        verified = getattr(redeemed, "receipt", None)
        pause = getattr(verified, "pause", None)
        decision = getattr(verified, "verified_decision", None)
        if not isinstance(pause, ApprovalPause) or not isinstance(decision, VerifiedApprovalDecision):
            raise ContractError("canonical first-party P01 TXT approval required")
        if (pause.run_id != command.run_id
                or pause.tool_id != "local.filesystem.read"
                or pause.requirement is not ApprovalRequirement.USER_CONFIRMATION
                or pause.approval_scope != ("filesystem.read",)
                or decision.pause_id != pause.pause_id
                or decision.outcome is not ApprovalOutcome.APPROVED):
            raise ContractError("canonical first-party P01 TXT approval required")

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
                raise ValueError("noncanonical selected TXT file READ")
            if not str(args["path_relative"]).lower().endswith(".txt"):
                raise ValueError("only exact TXT selected file can be read")
            req = LocalFileRequest(
                action_id=args["action_id"], run_id=args["run_id"],
                device_id=args["device_id"], root_ref=args["root_ref"],
                operation=LocalFileOperation.READ, path_relative=args["path_relative"],
                requested_at=datetime.fromisoformat(args["requested_at"].replace("Z", "+00:00")),
            )
            fingerprint = file_request_fingerprint(req)
            if (fingerprint != args["request_fingerprint"]
                    or fingerprint != scoped.request_fingerprint
                    or pause.invocation_sha256 != tool_invocation_digest(
                        windows_file_tool_invocation(req)
                    )):
                raise ValueError("Engine digest / canonical Windows request mismatch")
        except (TypeError, KeyError, AttributeError, ValueError) as exc:
            raise ContractError("Engine evidence does not bind canonical Windows READ") from exc

        now = admitted.admitted_at
        expires_at = min(
            pause.expires_at, decision.decided_at + _MAX_AGE, now + _MAX_AGE,
        )
        if (now < decision.decided_at - timedelta(seconds=30)
                or expires_at <= now
                or resolve_approval_pause(pause, decision, now=now).status
                is not ContinuationStatus.RESUMABLE):
            raise ContractError("verified text approval expired or invalid")

        from .local_agent_permissions import LocalPermissionRequest

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
        return TrustedP01VerifiedTextFilePlan(
            binding_ref=binding.binding_ref,
            command_id=command.command_id,
            tool_request_ref=command.tool_request_ref,
            run_id=command.run_id,
            request_id=admitted.request_id,
            revision_ref=command.revision_ref,
            command_fingerprint=admitted.command_fingerprint,
            sequence=command.sequence,
            file_request=req, file_evidence=authority,
        )


VERIFIED_ENGINE_TEXT_PLAN_MINTS_APPROVAL = False
VERIFIED_ENGINE_TEXT_PLAN_READS_FILES = False


def make_verified_text_plan_source() -> "VerifiedEngineTextReadPlanSource":
    """No-argument Resident factory (fail closed until authenticated host wiring)."""
    raise ContractError("authenticated P01 text evidence host is not configured")

