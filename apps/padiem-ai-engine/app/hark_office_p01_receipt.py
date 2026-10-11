"""#3580 Engine-produced approved Office READ receipt, trusted private sink ONLY.

No browser API, synthesized decision, device grant, Broker command or file bytes.
The Engine service supplies its ACTUAL first-party VERIFIED approval after
atomic continuation consumption, never an unverified user submission.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
import re

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement,
    VerifiedApprovalDecision, resolve_approval_pause,
    ContinuationStatus, tool_invocation_digest,
)
from padiem_ai_core.contracts import RunStatus
from padiem_ai_core.tool_runtime import ToolInvocation

from .hark_office_p01_tool_binding import APP_ID, FILE_SCOPE, READ_TOOL_ID

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NAME = re.compile(r"^[^<>:/\\|?*\x00-\x1f]{1,155}\.[xX][lL][sS][xX]?$")
_REQUIRED = frozenset({
    "action_id", "run_id", "device_id", "root_ref",
    "request_fingerprint", "operation", "path_relative", "requested_at",
    "content_bytes", "content_sha256", "directory_enumeration",
    "recursive_delete", "admin_elevation",
})


@dataclass(frozen=True, slots=True)
class ApprovedOfficeReadReceipt:
    """Canonical Engine grant *evidence*, not a local filesystem grant."""

    app_id: str
    continuation_ref: str
    pause: ApprovalPause
    verified_decision: VerifiedApprovalDecision
    exact_tool_arguments: tuple[tuple[str, Any], ...]

    def __post_init__(self) -> None:
        if self.app_id != APP_ID:
            raise ValueError("only a real Hark Office Engine app can produce a receipt")
        if type(self.continuation_ref) is not str or not self.continuation_ref.startswith("cont_"):
            raise ValueError("canonical consumed continuation required")
        if (not isinstance(self.pause, ApprovalPause)
                or not isinstance(self.verified_decision, VerifiedApprovalDecision)
                or self.pause.tool_id != READ_TOOL_ID
                or self.pause.requirement is not ApprovalRequirement.USER_CONFIRMATION
                or self.pause.approval_scope != (FILE_SCOPE,)
                or self.verified_decision.outcome is not ApprovalOutcome.APPROVED
                or self.verified_decision.pause_id != self.pause.pause_id):
            raise ValueError("exact verified Engine Office READ decision required")
        args = dict(self.exact_tool_arguments)
        if (not isinstance(self.exact_tool_arguments, tuple)
                or len(args) != len(self.exact_tool_arguments)
                or set(args) != _REQUIRED
                or any(type(args[k]) is not str or not args[k] or len(args[k]) > 128
                       for k in ("action_id", "run_id", "device_id", "root_ref"))
                or args["run_id"] != self.pause.run_id
                or type(args["request_fingerprint"]) is not str
                or not _SHA256.fullmatch(args["request_fingerprint"])
                or type(args["path_relative"]) is not str
                or not _NAME.fullmatch(args["path_relative"])
                or args["operation"] != "read"
                or args["content_bytes"] != 0 or args["content_sha256"] is not None
                or any(args[k] is not False for k in (
                    "directory_enumeration", "recursive_delete", "admin_elevation",
                ))):
            raise ValueError("Office receipt must bind exact selected-root READ arguments")
        try:
            requested_at = datetime.fromisoformat(args["requested_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("invalid requested_at") from exc
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError("Office request timestamp must be aware")
        if tool_invocation_digest(ToolInvocation(
            tool_id=READ_TOOL_ID, arguments=args,
        )) != self.pause.invocation_sha256:
            raise ValueError("Engine approval pause does not match this exact file")
        state = resolve_approval_pause(
            self.pause, self.verified_decision, now=self.verified_decision.decided_at,
        )
        if state.status is not ContinuationStatus.RESUMABLE:
            raise ValueError("unapproved or stale Engine receipt")

    @property
    def request_fingerprint(self) -> str:
        return dict(self.exact_tool_arguments)["request_fingerprint"]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "hark-office-engine-verified-read-receipt.v1",
            "app_id": self.app_id,
            "run_id": self.pause.run_id,
            "tool_id": READ_TOOL_ID,
            "request_fingerprint": self.request_fingerprint,
            "approval_pause_id": self.pause.pause_id,
            "verified_decision_id": self.verified_decision.decision_id,
            "device_permission_granted": False,
            "resident_dispatched": False,
            "file_bytes_in_receipt": False,
        }


class ApprovedOfficeReadReceiptSink(Protocol):
    """Server-injected durable private receiver; no public resolver or fake mint."""

    def record_verified_office_read(self, receipt: ApprovedOfficeReadReceipt) -> Any: ...


def prepare_approved_office_read_receipt(
    *, app_id: str, continuation_ref: str,
    pause: ApprovalPause, decision: VerifiedApprovalDecision,
    tool_arguments: Mapping[str, Any] | None, execution_status: RunStatus,
) -> ApprovedOfficeReadReceipt | None:
    """Fail closed for non-Office / deny / incomplete or forged continuation."""
    if app_id != APP_ID or pause.tool_id != READ_TOOL_ID:
        return None
    if decision.outcome is not ApprovalOutcome.APPROVED:
        return None
    if execution_status is not RunStatus.COMPLETED:
        raise ValueError("Engine Office READ confirmation did not complete")
    if not isinstance(tool_arguments, Mapping) or len(tool_arguments) != 1:
        raise ValueError("exactly one approved Office READ step required")
    only_step = next(iter(tool_arguments.values()))
    if not isinstance(only_step, Mapping):
        raise ValueError("approved Office step arguments missing")
    return ApprovedOfficeReadReceipt(
        app_id=app_id, continuation_ref=continuation_ref,
        pause=pause, verified_decision=decision,
        exact_tool_arguments=tuple(sorted(only_step.items())),
    )


OFFICE_RECEIPT_MINTS_LOCAL_GRANT = False
OFFICE_RECEIPT_EXPOSES_BROWSER_AUTHORITY = False
