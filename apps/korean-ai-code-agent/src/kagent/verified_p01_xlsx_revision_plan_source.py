"""#4434: the deployment-supplied P01 XLSX revision plan source.

This is the consumer the Resident starts when
``PADIEM_AGENT_XLSX_REVISION_PLAN_SOURCE`` names this module. It adds no approval
authority, no file access and no transport. It reads the closed revision envelope
that arrives with an admitted command, verifies it against that command, and
hands the lane a :class:`TrustedP01XlsxRevisionPlan`:

* the READ is attested now, because a read binds no content — the envelope's
  pause, decision and arguments are checked field by field, including the
  invocation digest the existing authority recomputes;
* the WRITE is *not* attested here. Its fingerprint and invocation digest bind
  the result bytes, which do not exist until the PC has read the workcopy,
  applied the reviewed edits and had them independently verified. So the plan
  carries an attester that resolves the write approval through the **existing**
  authenticated ``/v1/broker/p01-evidence`` route, keyed by the exact write
  ``request_fingerprint`` — the same route the resident execution lane and the
  browser.open slice already use.

A key is never a decision: the evidence the route returns must itself carry an
approved user-confirmation pause and decision naming that exact write invocation,
and it must be a different decision from the read. If the route has nothing, the
write is refused before any byte is committed and nothing is staged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import threading
from typing import Any, Callable

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement, ContinuationStatus,
    VerifiedApprovalDecision, resolve_approval_pause, tool_invocation_digest,
)

from .contracts import ContractError
from .local_agent_command_material import (
    XLSX_REVISION_POLICY_REF, XLSX_REVISION_RECEIPT_FORMAT,
    validate_xlsx_revision_receipt,
)
from .local_agent_control_plane_admission import ControlPlaneAdmittedExecutionReceipt
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope
from .local_agent_permissions import LocalPermissionRequest
from .local_resident_xlsx_revision_delivery import TrustedP01XlsxRevisionPlan
from .local_xlsx_revision_pdf import ReviewedCellRevision
from .local_xlsx_workcopy_roundtrip import revised_path_for
from .windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, WindowsFileAuthorityEvidence,
    file_request_fingerprint, windows_file_tool_invocation,
)

#: The one window the sibling TXT and Office plan sources already hold admitted
#: approvals to. No new limit is invented here.
_MAX_AGE = timedelta(minutes=5)
MAX_ATTESTED_REVISION_COMMANDS = 32
P01_EVIDENCE_ROUTE_REUSED = "/v1/broker/p01-evidence"

XLSX_REVISION_SOURCE_MINTS_APPROVAL = False
XLSX_REVISION_SOURCE_READS_FILES = False
XLSX_REVISION_SOURCE_ACCEPTS_BROWSER_PLAN = False


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parsed(text: str, field_name: str) -> datetime:
    try:
        return _aware(datetime.fromisoformat(text.replace("Z", "+00:00")), field_name)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} must be ISO-8601 text") from exc


def _pause_of(payload: dict[str, Any]) -> ApprovalPause:
    try:
        return ApprovalPause(
            pause_id=payload["pause_id"], run_id=payload["run_id"],
            agent_runtime_id=payload["agent_runtime_id"], tool_id=payload["tool_id"],
            invocation_sha256=payload["invocation_sha256"],
            requirement=ApprovalRequirement(payload["requirement"]),
            step_index=int(payload["step_index"]),
            created_at=_parsed(payload["created_at"], "pause.created_at"),
            expires_at=_parsed(payload["expires_at"], "pause.expires_at"),
            approval_scope=tuple(payload["approval_scope"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("P01 evidence carries an invalid approval pause") from exc


def _decision_of(payload: dict[str, Any]) -> VerifiedApprovalDecision:
    try:
        return VerifiedApprovalDecision(
            decision_id=payload["decision_id"], pause_id=payload["pause_id"],
            outcome=ApprovalOutcome(payload["outcome"]),
            authority_ref=payload["authority_ref"],
            evidence_ref=payload["evidence_ref"],
            decided_at=_parsed(payload["decided_at"], "decision.decided_at"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("P01 evidence carries an invalid approval decision") from exc


class P01EvidenceWriteAttester:
    """Resolve the deferred WRITE approval through the existing P01 evidence route.

    The request body is the same four correlation facts the resident execution
    lane and the browser.open slice send, unchanged, to the same loopback route.
    This class fetches and parses; it decides nothing and mints nothing, and a
    boundary that has not approved this exact write is a refusal.
    """

    def __init__(
        self, *, base_url: str, command_id: str, binding_ref: str, request_id: str,
        local_policy_ref: str = XLSX_REVISION_POLICY_REF,
        opener: Callable[[bytes], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._command_id = command_id
        self._binding_ref = binding_ref
        self._request_id = request_id
        self._policy_ref = local_policy_ref
        self._opener = opener
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._spent: set[str] = set()
        self._lock = threading.Lock()

    def _fetch(self, fingerprint: str) -> dict[str, Any]:
        body = json.dumps(
            {
                "command_id": self._command_id,
                "binding_ref": self._binding_ref,
                "request_fingerprint": fingerprint,
                "request_id": self._request_id,
            },
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        if self._opener is not None:
            return self._opener(body)
        if not self._base_url:
            raise ContractError("no configured P01 evidence boundary for the deferred write")
        import urllib.request

        request = urllib.request.Request(  # noqa: S310 - fixed loopback boundary
            f"{self._base_url}{P01_EVIDENCE_ROUTE_REUSED}", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def attest(self, request: LocalFileRequest) -> WindowsFileAuthorityEvidence:
        """One approval per write request, for the exact bytes now in hand."""

        if (not isinstance(request, LocalFileRequest)
                or request.operation is not LocalFileOperation.WRITE):
            raise ContractError("the write attester requires a canonical WRITE request")
        fingerprint = file_request_fingerprint(request)
        with self._lock:
            if fingerprint in self._spent:
                raise ContractError("XLSX write attestation has already been spent")
            if len(self._spent) + 1 > MAX_ATTESTED_REVISION_COMMANDS:
                raise ContractError("XLSX write attestation queue is full")
        try:
            payload = self._fetch(fingerprint)
        except ContractError:
            raise
        except Exception as exc:
            # A boundary that is unreachable, or that answers 404 because nobody
            # approved this exact write, is a refusal. The write never happens.
            raise ContractError(
                "the P01 evidence boundary did not attest this write") from exc
        if not isinstance(payload, dict):
            raise ContractError("the P01 evidence boundary returned no canonical envelope")
        envelope = payload.get("envelope")
        if not isinstance(envelope, dict):
            raise ContractError("the P01 evidence boundary returned no canonical envelope")
        for name in ("approval_pause", "approval_decision", "permission_requests",
                     "request_fingerprint", "local_policy_ref", "expires_at",
                     "evidence_ref"):
            if name not in envelope:
                # A partial answer is a refusal, never a crash the host would
                # have to guess the meaning of.
                raise ContractError(
                    "the P01 evidence boundary returned an incomplete envelope")

        pause = _pause_of(envelope["approval_pause"])
        decision = _decision_of(envelope["approval_decision"])
        if envelope["request_fingerprint"] != fingerprint:
            raise ContractError("P01 write evidence names a different write request")
        if pause.invocation_sha256 != tool_invocation_digest(
                windows_file_tool_invocation(request)):
            raise ContractError("P01 write evidence does not bind the verified result bytes")
        if (pause.tool_id != "local.filesystem.write"
                or pause.requirement is not ApprovalRequirement.USER_CONFIRMATION
                or pause.approval_scope != ("filesystem.write",)
                or pause.run_id != request.run_id
                or decision.pause_id != pause.pause_id
                or decision.outcome is not ApprovalOutcome.APPROVED):
            raise ContractError("canonical first-party P01 write confirmation required")
        if envelope.get("local_policy_ref") != self._policy_ref:
            raise ContractError("P01 write evidence names an unrecognized local policy")
        permission = next((item for item in envelope.get("permission_requests") or []
                           if isinstance(item, dict) and item.get("action_id")
                           == request.action_id), None)
        if not isinstance(permission, dict) or permission.get("target_ref") != fingerprint:
            raise ContractError("P01 write evidence carries no matching local permission")
        expires_at = min(pause.expires_at, decision.decided_at + _MAX_AGE,
                        _parsed(envelope["expires_at"], "evidence.expires_at"))
        now = _aware(self._clock(), "write attestation clock")
        if (now < decision.decided_at - timedelta(seconds=30) or expires_at <= now
                or resolve_approval_pause(pause, decision, now=now).status
                is not ContinuationStatus.RESUMABLE):
            raise ContractError("P01 write approval has expired or is not resumable")

        evidence = WindowsFileAuthorityEvidence(
            evidence_ref=decision.evidence_ref,
            request_fingerprint=fingerprint,
            permission_request=LocalPermissionRequest(
                action_id=request.action_id, run_id=request.run_id,
                device_id=request.device_id, capability=request.capability,
                target_ref=fingerprint, root_ref=request.root_ref,
            ),
            approval_pause=pause,
            approval_decision=decision,
            local_policy_ref=self._policy_ref,
            expires_at=expires_at,
        )
        with self._lock:
            self._spent.add(fingerprint)
        return evidence


@dataclass(frozen=True, slots=True)
class _AttestedCommand:
    """One admitted command's validated revision envelope, kept until the ACK."""

    envelope: dict[str, Any]
    request_id: str
    command_fingerprint: str


class VerifiedP01XlsxRevisionPlanSource:
    """The deployment's P01 revision material for exactly one acknowledged command."""

    def __init__(self, *, attester_factory: Callable[..., P01EvidenceWriteAttester],
                 local_policy_ref: str = XLSX_REVISION_POLICY_REF) -> None:
        if not callable(attester_factory) or not local_policy_ref:
            raise ContractError("a trusted write attester factory is required")
        self._attester_factory = attester_factory
        self._policy_ref = local_policy_ref
        self._lock = threading.Lock()
        self._attested: dict[tuple[str, str], _AttestedCommand] = {}

    def note_admitted(self, *, binding: Any, command: Any, request_id: str,
                      request_fingerprint: str, receipt: Any | None = None) -> bool:
        """Register a revision envelope at admission. Silent when this is not one.

        Absent or foreign-format material leaves the command on its ordinary
        path. Present-but-invalid revision material is refused: a malformed
        revision command must not execute and then discover it has no approval.
        """
        if not isinstance(receipt, dict) or receipt.get("format") != (
                XLSX_REVISION_RECEIPT_FORMAT):
            return False
        if (not isinstance(binding, DeviceBinding)
                or not isinstance(command, DeviceCommandEnvelope)):
            raise ContractError("canonical admitted Broker command required")
        if command.binding_ref != binding.binding_ref:
            raise ContractError("canonical admitted P01 command required")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ContractError("canonical admitted request id required")
        if (not isinstance(request_fingerprint, str)
                or len(request_fingerprint) != 64):
            raise ContractError("canonical admitted command fingerprint required")
        try:
            envelope = validate_xlsx_revision_receipt(receipt)
        except ContractError as exc:
            raise ContractError("XLSX revision approval receipt rejected") from exc
        args = envelope["source_approval"]["exact_tool_arguments"]
        if (envelope["command_id"] != command.command_id
                or envelope["request_id"] != request_id
                or args["run_id"] != command.run_id
                or args["device_id"] != binding.device_id):
            raise ContractError("XLSX revision receipt does not belong to this command")
        key = (binding.binding_ref, command.command_id)
        with self._lock:
            if key in self._attested:
                raise ContractError("XLSX revision command already attested")
            if len(self._attested) + 1 > MAX_ATTESTED_REVISION_COMMANDS:
                raise ContractError("XLSX revision attestation queue is full")
            self._attested[key] = _AttestedCommand(
                envelope=envelope, request_id=request_id,
                command_fingerprint=request_fingerprint,
            )
        return True

    def approved_revision_plan(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> TrustedPlan | None:
        """The plan for one acknowledged revision command, or None for any other."""

        if (not isinstance(binding, DeviceBinding)
                or not isinstance(command, DeviceCommandEnvelope)
                or not isinstance(receipt, ControlPlaneAdmittedExecutionReceipt)):
            raise ContractError("canonical admitted Broker command required")
        key = (binding.binding_ref, command.command_id)
        with self._lock:
            attested = self._attested.pop(key, None)
        if attested is None:
            return None
        fact = receipt.execution
        envelope = attested.envelope
        if (attested.request_id != fact.request_id
                or attested.command_fingerprint != fact.request_fingerprint):
            raise ContractError("XLSX revision attestation does not match the acknowledged command")

        args = dict(envelope["source_approval"]["exact_tool_arguments"])
        read_request = LocalFileRequest(
            action_id=args["action_id"], run_id=args["run_id"],
            device_id=args["device_id"], root_ref=args["root_ref"],
            operation=LocalFileOperation.READ, path_relative=args["path_relative"],
            requested_at=_parsed(args["requested_at"], "args.requested_at"),
        )
        if file_request_fingerprint(read_request) != args["request_fingerprint"]:
            raise ContractError("XLSX revision read fingerprint does not match its request")
        read_pause = _pause_of(envelope["source_approval"]["approval_pause"])
        read_decision = _decision_of(envelope["source_approval"]["approval_decision"])
        if (read_pause.invocation_sha256 != tool_invocation_digest(
                windows_file_tool_invocation(read_request))
                or read_pause.run_id != command.run_id
                or read_decision.pause_id != read_pause.pause_id
                or read_decision.outcome is not ApprovalOutcome.APPROVED):
            raise ContractError("XLSX revision read approval does not bind the canonical READ")

        now = receipt.acknowledged_at
        read_expires = min(read_pause.expires_at, read_decision.decided_at + _MAX_AGE,
                           now + _MAX_AGE, _parsed(envelope["expires_at"], "receipt.expires_at"))
        if (read_expires <= now
                or resolve_approval_pause(read_pause, read_decision, now=now).status
                is not ContinuationStatus.RESUMABLE):
            raise ContractError("XLSX revision read approval has expired before execution")

        revision = envelope["revision"]
        edits = tuple(
            ReviewedCellRevision(
                sheet_name=revision["sheet_name"], cell=item["cell"],
                previous_value=item["previous_value"],
                replacement_value=item["replacement_value"],
            ) for item in revision["edits"]
        )
        if not edits:
            raise ContractError("XLSX revision requires at least one reviewed cell")
        derived = revised_path_for(read_request.path_relative)
        if derived.replace("/", "\\").casefold() != revision["result_path_relative"].replace(
                "/", "\\").casefold():
            raise ContractError(
                "XLSX revision result name is not the derived revised workcopy")

        read_evidence = WindowsFileAuthorityEvidence(
            evidence_ref=read_decision.evidence_ref,
            request_fingerprint=args["request_fingerprint"],
            permission_request=LocalPermissionRequest(
                action_id=read_request.action_id, run_id=read_request.run_id,
                device_id=read_request.device_id, capability=read_request.capability,
                target_ref=args["request_fingerprint"], root_ref=read_request.root_ref,
            ),
            approval_pause=read_pause,
            approval_decision=read_decision,
            local_policy_ref=self._policy_ref,
            expires_at=read_expires,
        )
        return TrustedP01XlsxRevisionPlan(
            binding_ref=binding.binding_ref,
            command_id=command.command_id,
            tool_request_ref=command.tool_request_ref,
            run_id=command.run_id,
            request_id=fact.request_id,
            revision_ref=command.revision_ref,
            command_fingerprint=fact.request_fingerprint,
            sequence=command.sequence,
            read_request=read_request,
            read_evidence=read_evidence,
            derived_path_relative=derived,
            write_action_id=revision["write_action_id"],
            write_requested_at=_parsed(revision["write_requested_at"],
                                       "revision.write_requested_at"),
            write_attester=self._attester_factory(
                command_id=command.command_id, binding_ref=binding.binding_ref,
                request_id=fact.request_id, local_policy_ref=self._policy_ref,
            ),
            edits=edits,
        )

    def safe_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "contract_version": "claw-verified-p01-xlsx-revision-plan-source.v1",
                "attested_command_count": len(self._attested),
                "approval_authority_created": False,
                "write_attested_before_result_bytes": False,
                "file_reads_performed": False,
                "browser_file_plan_accepted": XLSX_REVISION_SOURCE_ACCEPTS_BROWSER_PLAN,
            }


def make_p01_xlsx_revision_plan_source() -> VerifiedP01XlsxRevisionPlanSource:
    """No-argument Resident factory for ``module:attribute`` configuration.

    The environment names this module and nothing else: no path, no approval, no
    credential. The write attester reads the boundary from
    ``PADIEM_AGENT_BROKER_URL``, the same value the resident entry and the
    browser.open slice already use, so there is no second endpoint to configure
    and no second authority to trust.
    """

    import os

    def attester_factory(**scoped: Any) -> P01EvidenceWriteAttester:
        return P01EvidenceWriteAttester(
            base_url=os.environ.get("PADIEM_AGENT_BROKER_URL") or "", **scoped,
        )

    return VerifiedP01XlsxRevisionPlanSource(attester_factory=attester_factory)
