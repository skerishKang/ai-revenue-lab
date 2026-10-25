"""#4434: the Resident lane that revises an approved XLSX workcopy and stages it.

This is the connection between the acknowledged Broker command and the revision
host already built in ``local_xlsx_workcopy_roundtrip``. It adds no file
authority, no approval and no transport:

* the canonical P01 plan for exactly the acknowledged command comes from a
  deployment-injected trusted source, the same shape the Office pair lane uses;
* the existing ``P01LocalPermissionWindowsFileAuthorizationPort`` remains the
  only file authority, and re-evaluates local policy plus the pause/decision for
  both the READ and the derived WRITE;
* ``LocalOfficeChunkPublisher`` remains the only outbound byte path, so the
  broker still validates the acknowledged command and the device authority.

Three ordering facts the pieces above could not express on their own live here.

A revision command is consumed exactly once per ``(binding, command)`` pair, so a
reconnect or duplicate delivery cannot revise the file a second time.

The WRITE is attested *after* its bytes exist. The write request fingerprint and
the tool-invocation digest both bind ``content_bytes``/``content_sha256``
(``windows_local_filesystem.py:165-199``), so nothing that has not produced the
result can honestly approve it. The lane therefore prepares and independently
verifies the revised bytes, resolves the write evidence through the trusted
attester for exactly that fingerprint, and only then lets the file authority
commit the derived workcopy — a refusal writes nothing and stages nothing.

A fingerprint is a key, never a decision. The attester's answer must carry its
own approved pause and decision naming that invocation, and the read and write
halves must be two distinct decisions.

The Python value editor, the independent verifier and the original-preserving
path rule come from ``local_xlsx_python_copy_editor`` and
``local_xlsx_workcopy_roundtrip`` unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import threading
from pathlib import PureWindowsPath
from typing import Any, Callable, Protocol

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement, VerifiedApprovalDecision,
    tool_invocation_digest,
)

from .contracts import ContractError
from .local_agent_control_plane_admission import ControlPlaneAdmittedExecutionReceipt
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope
from .local_office_chunk_publisher import LocalOfficeChunkPublisher
from .local_xlsx_revision_pdf import ReviewedCellRevision
from .local_xlsx_workcopy_roundtrip import (
    LocalXlsxWorkcopyRoundtrip, revised_path_for,
    revise_and_stage_approved_xlsx_workcopy,
)
from .windows_local_executor import WindowsExecutionTermination
from .windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, P01LocalPermissionWindowsFileAuthorizationPort,
    WindowsFileAuthorityEvidence, WindowsSelectedRootFileRuntime,
    file_request_fingerprint, windows_file_tool_invocation,
)

MAX_PREAPPROVED_XLSX_REVISION_PLANS = 32
_MAX_CLOCK_SKEW = timedelta(minutes=5)

RESIDENT_XLSX_REVISION_LANE_PRODUCTION_CONFIGURED = False
XLSX_REVISION_FAKE_GRANT_ACCEPTED = False
XLSX_REVISION_WRITES_THE_ORIGINAL = False
XLSX_REVISION_MINTS_APPROVAL = False


@dataclass(frozen=True, slots=True)
class TrustedP01XlsxRevisionPlan:
    """Attested P01 material for one revision of one acknowledged command.

    The trusted host supplies the approved READ with its evidence, the reviewed
    literal edits, and the derived workcopy name plus the write action the PC will
    name when it asks for the write attestation. This object creates no approval:
    the read pause, decision and local permission evidence are the ones the
    existing P01 authority already issued, and the write half is attested by the
    injected attester only after the result bytes exist.
    """

    binding_ref: str
    command_id: str
    tool_request_ref: str
    run_id: str
    request_id: str
    revision_ref: str
    command_fingerprint: str
    sequence: int
    read_request: LocalFileRequest
    read_evidence: WindowsFileAuthorityEvidence
    derived_path_relative: str
    write_action_id: str
    write_requested_at: datetime
    write_attester: Any
    edits: tuple[ReviewedCellRevision, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.read_request, LocalFileRequest):
            raise ContractError("canonical XLSX read request required")
        if not isinstance(self.read_evidence, WindowsFileAuthorityEvidence):
            raise ContractError("canonical P01 evidence for the approved READ required")
        if (self.read_request.operation is not LocalFileOperation.READ
                or not self.read_request.path_relative.lower().endswith(".xlsx")):
            raise ContractError("XLSX revision plan requires an approved XLSX READ")
        if self.read_evidence.request_fingerprint != file_request_fingerprint(
                self.read_request):
            raise ContractError("P01 evidence does not match its file request")
        if self.read_request.run_id != self.run_id:
            raise ContractError("file request is foreign to the plan run")

        derived = revised_path_for(self.read_request.path_relative)
        if _normalize(self.derived_path_relative) != _normalize(derived):
            raise ContractError(
                "XLSX revision plan must target the derived revised workcopy")
        if not isinstance(self.write_action_id, str) or not self.write_action_id.strip():
            raise ContractError("the deferred WRITE needs its own bounded action id")
        if self.write_action_id == self.read_request.action_id:
            raise ContractError("read and write must be distinct actions")
        if (not isinstance(self.write_requested_at, datetime)
                or self.write_requested_at.tzinfo is None
                or self.write_requested_at.utcoffset() is None):
            raise ContractError("the deferred WRITE needs a timezone-aware requested_at")
        if not callable(getattr(self.write_attester, "attest", None)):
            raise ContractError("a trusted write attester is required")

        edits = tuple(self.edits)
        if not edits or any(not isinstance(item, ReviewedCellRevision) for item in edits):
            raise ContractError("reviewed cell revisions required")
        object.__setattr__(self, "edits", edits)
        if len(self.command_fingerprint) != 64:
            raise ContractError("canonical command fingerprint required")
        if (isinstance(self.sequence, bool) or not isinstance(self.sequence, int)
                or self.sequence <= 0):
            raise ContractError("positive canonical command sequence required")

    def write_request_for(self, content: bytes) -> LocalFileRequest:
        """The WRITE request for bytes the editor produced and the verifier accepted."""

        if not isinstance(content, bytes) or not content:
            raise ContractError("verified result bytes are required before a WRITE exists")
        return LocalFileRequest(
            action_id=self.write_action_id, run_id=self.run_id,
            device_id=self.read_request.device_id, root_ref=self.read_request.root_ref,
            operation=LocalFileOperation.WRITE, path_relative=self.derived_path_relative,
            requested_at=self.write_requested_at, content=content,
        )


class TrustedP01XlsxRevisionPlanSource(Protocol):
    """Deployment-owned P01 authority material for one acknowledged command.

    Returns None when the command is not an approved XLSX revision. It must not
    read a model answer, walk a directory or mint user consent.
    """

    def approved_revision_plan(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> TrustedP01XlsxRevisionPlan | None: ...


class TrustedP01XlsxRevisionBridge:
    """One-shot evidence source for the plan's READ and WRITE, per command.

    The revision of one acknowledged command runs once: a reconnect, a duplicate
    delivery or any second attempt on the same ``(binding, command)`` is refused
    before the file is read again, so the existing Broker ACK truth is never
    turned into a second execution and a finished result is never re-written.
    """

    def __init__(self, *, source: TrustedP01XlsxRevisionPlanSource) -> None:
        if not callable(getattr(source, "approved_revision_plan", None)):
            raise ContractError("trusted XLSX revision plan source required")
        self._source = source
        self._lock = threading.Lock()
        self._pending: dict[str, WindowsFileAuthorityEvidence] = {}
        self._consumed: set[tuple[str, str]] = set()
        self._plan: TrustedP01XlsxRevisionPlan | None = None

    def plan_for_completed_command(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> TrustedP01XlsxRevisionPlan | None:
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
            raise ContractError("successful exact Broker ACK required before revision")
        key = (binding.binding_ref, command.command_id)
        with self._lock:
            if key in self._consumed:
                raise ContractError("XLSX revision command already consumed")
            self._consumed.add(key)
        plan = self._source.approved_revision_plan(
            binding=binding, command=command, receipt=receipt,
        )
        if plan is None:
            with self._lock:
                self._consumed.discard(key)
            return None
        if not isinstance(plan, TrustedP01XlsxRevisionPlan):
            raise ContractError("XLSX revision source returned invalid authority material")
        now = receipt.acknowledged_at
        if (plan.binding_ref != binding.binding_ref
                or plan.command_id != command.command_id
                or plan.tool_request_ref != command.tool_request_ref
                or plan.run_id != command.run_id
                or plan.request_id != fact.request_id
                or plan.revision_ref != command.revision_ref
                or plan.command_fingerprint != fact.request_fingerprint
                or plan.sequence != command.sequence
                or plan.read_request.device_id != binding.device_id
                or plan.read_request.requested_at > now + _MAX_CLOCK_SKEW
                or plan.read_evidence.expires_at <= now - _MAX_CLOCK_SKEW
                or plan.read_evidence.approval_pause.run_id != command.run_id
                or _normalize(plan.derived_path_relative) != _normalize(
                    revised_path_for(plan.read_request.path_relative))):
            raise ContractError("XLSX revision plan/approval correlation invalid")
        with self._lock:
            if len(self._pending) + 1 > MAX_PREAPPROVED_XLSX_REVISION_PLANS:
                raise ContractError("XLSX revision evidence queue full")
            fingerprint = file_request_fingerprint(plan.read_request)
            if fingerprint in self._pending:
                raise ContractError("XLSX revision evidence already queued")
            self._pending[fingerprint] = plan.read_evidence
            self._plan = plan
        return plan

    def expect_write(self, request: LocalFileRequest, *, now: datetime
                     ) -> WindowsFileAuthorityEvidence:
        """Attest the deferred WRITE for bytes that now exist, and queue it once.

        Called after the editor produced and the independent verifier accepted the
        result. The attester is the deployment's trusted P01 evidence route; its
        answer must itself carry an approved decision naming this exact
        invocation. Nothing here turns a fingerprint into an approval.
        """
        with self._lock:
            plan = self._plan
        if plan is None:
            raise ContractError("no XLSX revision plan is registered for this command")
        if (not isinstance(request, LocalFileRequest)
                or request.operation is not LocalFileOperation.WRITE
                or _normalize(request.path_relative) != _normalize(plan.derived_path_relative)
                or request.action_id != plan.write_action_id
                or request.run_id != plan.run_id
                or request.device_id != plan.read_request.device_id
                or request.root_ref != plan.read_request.root_ref
                or request.requested_at != plan.write_requested_at
                or not isinstance(request.content, bytes) or not request.content):
            raise ContractError("the deferred WRITE does not match the registered plan")

        fingerprint = file_request_fingerprint(request)
        evidence = plan.write_attester.attest(request)
        if not isinstance(evidence, WindowsFileAuthorityEvidence):
            raise ContractError("XLSX write attester returned invalid evidence")
        if evidence.request_fingerprint != fingerprint:
            raise ContractError("XLSX write evidence does not name this write request")
        pause = evidence.approval_pause
        decision = evidence.approval_decision
        if (not isinstance(pause, ApprovalPause)
                or not isinstance(decision, VerifiedApprovalDecision)):
            raise ContractError("XLSX write requires a canonical P01 pause and decision")
        if (pause.tool_id != "local.filesystem.write"
                or pause.requirement is not ApprovalRequirement.USER_CONFIRMATION
                or pause.approval_scope != ("filesystem.write",)
                or pause.run_id != plan.run_id
                or decision.pause_id != pause.pause_id
                or decision.outcome is not ApprovalOutcome.APPROVED):
            raise ContractError("XLSX write evidence is not an approved write confirmation")
        if pause.invocation_sha256 != tool_invocation_digest(
                windows_file_tool_invocation(request)):
            raise ContractError("XLSX write evidence does not bind the verified result bytes")
        if decision.decision_id == plan.read_evidence.approval_decision.decision_id:
            raise ContractError("read and write must be two distinct P01 decisions")
        if (not isinstance(now, datetime) or now.tzinfo is None
                or now.utcoffset() is None):
            raise ContractError("a trusted current clock is required for the write attestation")
        if evidence.expires_at <= now or pause.expires_at <= now:
            raise ContractError("XLSX write approval has expired before the write")

        with self._lock:
            if fingerprint in self._pending:
                raise ContractError("XLSX revision evidence already queued")
            if len(self._pending) + 1 > MAX_PREAPPROVED_XLSX_REVISION_PLANS:
                raise ContractError("XLSX revision evidence queue full")
            self._pending[fingerprint] = evidence
        return evidence

    def note_admitted(self, **admitted: Any) -> bool:
        """Give the trusted source the revision material that rode this command."""

        note = getattr(self._source, "note_admitted", None)
        if not callable(note):
            return False
        return bool(note(**admitted))

    def resolve(self, request_fingerprint: str) -> WindowsFileAuthorityEvidence:
        if type(request_fingerprint) is not str or len(request_fingerprint) != 64:
            raise ContractError("exact file request SHA-256 required")
        with self._lock:
            evidence = self._pending.pop(request_fingerprint, None)
        if evidence is None:
            raise ContractError("XLSX revision requires unconsumed P01 evidence")
        return evidence

    def safe_dict(self) -> dict:
        with self._lock:
            return {
                "contract_version": "claw-trusted-p01-xlsx-revision-bridge.v1",
                "pending_evidence_count": len(self._pending),
                "consumed_command_count": len(self._consumed),
                "approval_authority_created": False,
                "device_credential_stored": False,
                "raw_file_bytes_stored": False,
                "browser_file_plan_accepted": False,
                "one_shot": True,
            }


class ResidentXlsxRevisionStager:
    """Post-ACK executor of one approved revision, staged through the broker."""

    def __init__(
        self, *,
        device: Any,
        bridge: TrustedP01XlsxRevisionBridge,
        file_authorization_port: Any,
        publisher: LocalOfficeChunkPublisher,
        clock: Callable[[], datetime],
    ) -> None:
        if (not isinstance(publisher, LocalOfficeChunkPublisher)
                or not isinstance(bridge, TrustedP01XlsxRevisionBridge)
                or not callable(clock)):
            raise ContractError("canonical publisher, revision bridge and trusted clock required")
        if type(file_authorization_port) is not P01LocalPermissionWindowsFileAuthorizationPort:
            # The test adapters mint their own grant. The revision lane may only
            # run on the canonical P01 plus recomputed local policy authority.
            raise ContractError("canonical P01 file authorization port required")
        self._runtime = WindowsSelectedRootFileRuntime(
            device=device, authorization_port=file_authorization_port,
        )
        self._device = device
        self._bridge = bridge
        self._publisher = publisher
        self._clock = clock

    def note_admitted(self, **admitted: Any) -> bool:
        """Forward admitted revision material to the trusted source, before execution."""

        return self._bridge.note_admitted(**admitted)

    def on_acknowledged(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt, credential: bytes,
    ) -> LocalXlsxWorkcopyRoundtrip | None:
        if (not isinstance(binding, DeviceBinding)
                or not isinstance(command, DeviceCommandEnvelope)
                or not isinstance(receipt, ControlPlaneAdmittedExecutionReceipt)
                or type(credential) is not bytes or not credential):
            raise ContractError("canonical broker receipt/binding required before revision")
        fact = receipt.execution
        if (fact.command_id != command.command_id
                or fact.run_id != command.run_id
                or fact.binding_ref != binding.binding_ref
                or len(fact.request_fingerprint) != 64
                or fact.revision_ref != command.revision_ref
                or fact.tool_request_ref != command.tool_request_ref
                or fact.sequence != command.sequence
                or fact.termination is not WindowsExecutionTermination.EXITED
                or fact.exit_code != 0
                or not receipt.evidence_ref
                or not fact.admission_ref):
            raise ContractError("exact acknowledged successful revision command is required")

        plan = self._bridge.plan_for_completed_command(
            binding=binding, command=command, receipt=receipt,
        )
        if plan is None:
            return None

        now = self._clock()
        if (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
                or now < receipt.acknowledged_at - _MAX_CLOCK_SKEW):
            raise ContractError("current trusted post-ACK local file clock required")

        ref = sha256(f"{command.command_id}:{plan.read_request.action_id}".encode()).hexdigest()[:28]

        def result_request(content: bytes, path: str) -> LocalFileRequest:
            # Reached only after the independent verifier accepted these bytes.
            # The WRITE is named now, attested now, and only then written.
            if _normalize(path) != _normalize(plan.derived_path_relative):
                raise ContractError("derived result path does not match the registered plan")
            request = plan.write_request_for(content)
            self._bridge.expect_write(request, now=now)
            return request

        roundtrip = revise_and_stage_approved_xlsx_workcopy(
            runtime=self._runtime, device=self._device,
            source_request=plan.read_request,
            result_request_factory=result_request,
            edits=plan.edits,
            workspace_ref=binding.workspace_ref,
            source_artifact_id=f"resident_xlsx_revision_source_{ref}",
            result_artifact_id=f"resident_xlsx_revision_result_{ref}",
            binding_ref=binding.binding_ref,
            command_id=command.command_id,
            credential=credential,
            now=now,
            publisher=self._publisher,
        )
        if (roundtrip.revised.run_ref != command.run_id
                or roundtrip.command_id != command.command_id
                or roundtrip.source.record.workspace_ref != binding.workspace_ref
                or roundtrip.staging.artifact_id != roundtrip.revised.artifact_id):
            raise ContractError("revision staging did not correlate to the acknowledged run")
        if _normalize(roundtrip.written.path_relative) != _normalize(roundtrip.revised_relative_path):
            raise ContractError("written path is not the derived revised workcopy")
        if PureWindowsPath(roundtrip.written.path_relative).name.casefold() == (
                roundtrip.source.record.filename.casefold()):
            raise ContractError("revision must never write the original file")
        return roundtrip


def compose_resident_xlsx_revision_stager(
    *, device: Any, revision_plan_source: Any, permission_profile: Any,
    publisher_config: Any, transport: Any, clock: Callable[[], datetime],
) -> ResidentXlsxRevisionStager:
    """Explicit trusted Resident composition; no ambient revision switch.

    The bridge is the evidence port of the existing canonical P01 file
    authorization port, so every READ and the derived WRITE are re-checked
    against local policy and the pause/decision the P01 host already issued.
    """
    from .local_agent import LocalAgentDeviceProfile, LocalAgentPlatform

    if (not isinstance(device, LocalAgentDeviceProfile)
            or device.platform is not LocalAgentPlatform.WINDOWS
            or not callable(getattr(revision_plan_source, "approved_revision_plan", None))
            or not callable(clock)):
        raise ContractError("current P01 selected-root revision authority required")
    bridge = TrustedP01XlsxRevisionBridge(source=revision_plan_source)
    return ResidentXlsxRevisionStager(
        device=device,
        bridge=bridge,
        file_authorization_port=P01LocalPermissionWindowsFileAuthorizationPort(
            permission_profile=permission_profile, evidence_port=bridge,
        ),
        publisher=LocalOfficeChunkPublisher(transport=transport, config=publisher_config),
        clock=clock,
    )


def _normalize(value: str) -> str:
    return value.replace("/", "\\").strip().casefold()
