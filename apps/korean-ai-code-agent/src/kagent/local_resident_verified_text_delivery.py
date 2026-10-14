"""#4139 — post-ACK Windows TXT READ → canonical verified text result.

This is the Resident-side producer for the one contract LOCAL1's #4705 broker
store accepts: a bounded UTF-8 body, correlated to the *already successfully
acknowledged* command that produced it, on the one canonical device route.

Nothing new is minted:

* the **same** ``WindowsSelectedRootFileRuntime`` performs the read, so the
  **same** ``P01LocalPermissionWindowsFileAuthorizationPort`` re-checks the
  current P01 approval, local permission, selected root, symlink/reparse escape,
  allowed operation and file size before a single byte is read;
* the **same** ``TrustedP01OfficeFilePlanBridge`` pattern supplies the exact
  authorized READ request for the acknowledged command — here pinned to a text
  file instead of a workbook, with its own one-shot plan/evidence queue;
* the **same** ``LocalAgentTextResultPublisher`` (pinned TLS, one route) sends
  the result. There is no second TXT upload path and no second file authority.

Order, and why it is this order: the broker's own write gate for #4705 accepts a
result **only** for a command that is already ``ACKNOWLEDGED`` with ``exited``
and exit code 0 (the Office staging gate, unchanged), so a Windows read result
is produced strictly *after* the original task's successful acknowledgement.
Inside that post-ACK step the ``pending`` declaration still goes out **before**
the body travels — the reader may then answer "this read is still coming"
instead of reconstructing a terminal-only message — but only for a read that
actually produced a bounded body.

    POST_ACK_ONLY=1 · PENDING_BEFORE_BODY=1 · SECOND_TXT_UPLOAD_PATH=0
    TRUNCATION_AS_COMPLETENESS=0 · GENERIC_STDOUT_TRUSTED=0

Contract junction (LOCAL1 #4705): the broker's write gate requires
``ACKNOWLEDGED`` for the ``pending`` state as well, so a declaration cannot be
sent before the completion ACK as an earlier draft of this lane assumed. If the
declaration must precede the ACK, #4705's gate has to admit ``pending`` for an
admitted-but-unacknowledged command; until it does, the earliest admissible
order is the one implemented here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from .contracts import ContractError
from .local_agent_control_plane_admission import ControlPlaneAdmittedExecutionReceipt
from .local_agent_control_plane_https import (
    PinnedHttpsJsonRequestPort,
    StdlibPinnedHttpsJsonRequestPort,
)
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope
from .local_agent_secure_transport import OutboundTransportConfig
from .local_agent_verified_text_result import (
    LocalAgentTextResultPublisher,
    VerifiedTextResult,
    VerifiedTextResultRefused,
    build_verified_text_result,
)
from .windows_local_executor import WindowsExecutionTermination
from .windows_local_filesystem import (
    LocalFileOperation,
    LocalFileRequest,
    WindowsFileAuthorityEvidence,
    WindowsSelectedRootFileRuntime,
    file_request_fingerprint,
)

MAX_PREAPPROVED_TEXT_PLANS = 32
_MAX_CLOCK_SKEW = timedelta(minutes=5)
#: The only file kind this lane may return as a text read. A text result is a
#: bounded read result, never a binary/document lane (that stays #3580 Office).
TEXT_READ_SUFFIX = ".txt"


@dataclass(frozen=True, slots=True)
class TrustedP01VerifiedTextFilePlan:
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
            raise ContractError("canonical P01 text file request required")
        if not isinstance(self.file_evidence, WindowsFileAuthorityEvidence):
            raise ContractError("canonical P01 text approval evidence required")
        if (
            self.file_request.operation is not LocalFileOperation.READ
            or not self.file_request.path_relative.lower().endswith(TEXT_READ_SUFFIX)
            or self.file_request.run_id != self.run_id
            or self.file_evidence.request_fingerprint
            != file_request_fingerprint(self.file_request)
            or len(self.command_fingerprint) != 64
            or isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence <= 0
        ):
            raise ContractError("text file plan not bound to an exact authorized READ")


class TrustedP01VerifiedTextPlanSource(Protocol):
    """Injected local P01 authority material; no JSON/env/browser fallback."""

    def approved_plan(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> TrustedP01VerifiedTextFilePlan | None: ...


class TrustedP01VerifiedTextFilePlanBridge:
    """One-shot host adapter: the authorized text READ plus its P01 evidence.

    The evidence is consumed by the existing Windows file authorization port,
    which independently re-evaluates local policy and the P01 pause/decision.
    Nothing here bypasses or replaces that port.
    """

    def __init__(self, *, source: TrustedP01VerifiedTextPlanSource) -> None:
        if not callable(getattr(source, "approved_plan", None)):
            raise ContractError("trusted P01 verified-text plan source required")
        self._source = source
        self._pending: dict[str, WindowsFileAuthorityEvidence] = {}
        self._consumed_commands: set[tuple[str, str]] = set()

    def request_for_completed_command(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> LocalFileRequest | None:
        if (
            not isinstance(binding, DeviceBinding)
            or not isinstance(command, DeviceCommandEnvelope)
            or not isinstance(receipt, ControlPlaneAdmittedExecutionReceipt)
        ):
            raise ContractError("canonical P01 command required")
        fact = receipt.execution
        if (
            fact.command_id != command.command_id
            or fact.run_id != command.run_id
            or fact.binding_ref != binding.binding_ref
            or fact.tool_request_ref != command.tool_request_ref
            or fact.revision_ref != command.revision_ref
            or fact.sequence != command.sequence
            or fact.termination is not WindowsExecutionTermination.EXITED
            or fact.exit_code != 0
        ):
            raise ContractError("successful exact Broker ACK required before text READ")
        key = (binding.binding_ref, command.command_id)
        if key in self._consumed_commands:
            raise ContractError("text command file plan already consumed")
        self._consumed_commands.add(key)
        plan = self._source.approved_plan(
            binding=binding, command=command, receipt=receipt,
        )
        if plan is None:
            return None
        if not isinstance(plan, TrustedP01VerifiedTextFilePlan):
            raise ContractError("text plan source returned invalid authority material")
        request, evidence = plan.file_request, plan.file_evidence
        now = receipt.acknowledged_at
        if (
            plan.binding_ref != binding.binding_ref
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
            or request.requested_at > now + _MAX_CLOCK_SKEW
        ):
            raise ContractError("text P01 plan/approval correlation invalid")
        fingerprint = file_request_fingerprint(request)
        if len(self._pending) >= MAX_PREAPPROVED_TEXT_PLANS or fingerprint in self._pending:
            raise ContractError("text P01 evidence queue full/conflicting")
        self._pending[fingerprint] = evidence
        return request

    def resolve(self, request_fingerprint: str) -> WindowsFileAuthorityEvidence:
        if type(request_fingerprint) is not str or len(request_fingerprint) != 64:
            raise ContractError("exact file request SHA-256 required")
        evidence = self._pending.pop(request_fingerprint, None)
        if evidence is None:
            raise ContractError("text READ requires unconsumed P01 evidence")
        return evidence

    def safe_dict(self) -> dict:
        return {
            "contract_version": "claw-trusted-p01-verified-text-file-plan-bridge.v1",
            "pending_evidence_count": len(self._pending),
            "approval_authority_created": False,
            "device_credential_stored": False,
            "raw_file_bytes_stored": False,
            "browser_file_plan_accepted": False,
            "text_files_only": True,
            "one_shot": True,
        }


class WindowsVerifiedTextProducer:
    """Read the *approved* text file and bound the result for transport."""

    def __init__(
        self,
        *,
        files: WindowsSelectedRootFileRuntime,
        requests: Any,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(files, WindowsSelectedRootFileRuntime):
            raise ContractError("canonical selected-root file runtime required")
        if not callable(getattr(requests, "request_for_completed_command", None)):
            raise ContractError("trusted approved text READ request port required")
        if not callable(clock):
            raise ContractError("trusted post-ACK local clock required")
        self._files = files
        self._requests = requests
        self._clock = clock

    def approved_request(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> LocalFileRequest | None:
        """The exact authorized READ for this command, or None when it is not one."""
        request = self._requests.request_for_completed_command(
            binding=binding, command=command, receipt=receipt,
        )
        if request is None:
            return None
        if (
            not isinstance(request, LocalFileRequest)
            or request.operation is not LocalFileOperation.READ
            or request.run_id != command.run_id
            or request.device_id != binding.device_id
            or not request.path_relative.lower().endswith(TEXT_READ_SUFFIX)
        ):
            raise ContractError("text producer received foreign/non-read file request")
        return request

    def read_verified_text(
        self,
        *,
        request: LocalFileRequest,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
        now: datetime | None = None,
    ) -> VerifiedTextResult:
        """Perform the real P01-authorized READ and bound what came back."""
        moment = now if now is not None else self._clock()
        if (
            not isinstance(moment, datetime)
            or moment.tzinfo is None
            or moment.utcoffset() is None
            or moment < receipt.acknowledged_at - _MAX_CLOCK_SKEW
        ):
            raise ContractError("current trusted post-ACK local file clock required")
        # The selected-root runtime checks the current P01 grant, the device,
        # the selected root, symlink/reparse escape, the allowed operation and
        # the size limit. Its result is canonical, not a raw arbitrary path.
        result = self._files.perform(request, now=moment)
        if (
            result.operation is not LocalFileOperation.READ
            or result.run_id != command.run_id
            or result.device_id != binding.device_id
            or result.action_id != request.action_id
            or result.path_relative != request.path_relative
            or not isinstance(result.content, (bytes, bytearray))
        ):
            raise ContractError("text READ did not return the authorized file bytes")
        raw = bytes(result.content)
        # The read's own claims must agree with the bytes actually returned
        # before those bytes may be described to Claw as this file's content.
        if result.bytes_count != len(raw) or result.content_sha256 != hashlib.sha256(raw).hexdigest():
            raise ContractError("text READ bytes do not match the read receipt")
        try:
            built = build_verified_text_result(
                command_id=command.command_id,
                run_id=command.run_id,
                request_fingerprint=receipt.execution.request_fingerprint,
                content=raw,
            )
        except VerifiedTextResultRefused as exc:
            # Too large or not UTF-8: refused, never truncated or transcoded.
            raise ContractError(f"verified text result refused: {exc}") from exc
        return built

    def completed_text(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> VerifiedTextResult | None:
        """Plan + read + bound, for callers that do not need the pending step."""
        request = self.approved_request(binding=binding, command=command, receipt=receipt)
        if request is None:
            return None
        return self.read_verified_text(
            request=request, binding=binding, command=command, receipt=receipt,
        )


@dataclass(frozen=True, slots=True)
class TrustedVerifiedTextDelivery:
    """What actually left this PC. Never the body, never a false completion."""

    result: VerifiedTextResult
    pending_declared: bool
    content_uploaded: bool
    content_receipt: dict[str, Any]

    def __post_init__(self) -> None:
        if self.content_uploaded is not True or self.pending_declared is not True:
            raise ContractError(
                "a text delivery is only reported after pending and body were stored"
            )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-resident-verified-text-delivery.v1",
            "pending_declared": True,
            "content_uploaded": True,
            "pending_before_body": True,
            "content_present": self.content_receipt.get("content_present") is True,
            "content_bytes": self.result.content_bytes,
            "content_sha256": self.result.content_sha256,
            "command_id": self.result.command_id,
            "run_id": self.result.run_id,
            "returned_to_claw": True,
            "generic_stdout_trusted": False,
            "truncated_as_complete": False,
        }


class ResidentVerifiedTextPublisher:
    """Post-ACK sender for one P01-approved text read (#4139)."""

    def __init__(
        self,
        *,
        approved_text: WindowsVerifiedTextProducer,
        publisher: LocalAgentTextResultPublisher,
    ) -> None:
        if not isinstance(approved_text, WindowsVerifiedTextProducer):
            raise ContractError("canonical verified-text producer required")
        if not isinstance(publisher, LocalAgentTextResultPublisher):
            raise ContractError("canonical verified text result publisher required")
        self._approved_text = approved_text
        self._publisher = publisher

    def on_acknowledged(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
        credential: bytes,
    ) -> TrustedVerifiedTextDelivery | None:
        """Return the real text to the broker, or None for a non-text command."""
        if (
            not isinstance(binding, DeviceBinding)
            or not isinstance(command, DeviceCommandEnvelope)
            or not isinstance(receipt, ControlPlaneAdmittedExecutionReceipt)
            or type(credential) is not bytes
            or not credential
        ):
            raise ContractError("canonical broker receipt/binding required before text delivery")
        fact = receipt.execution
        if (
            fact.command_id != command.command_id
            or fact.run_id != command.run_id
            or fact.binding_ref != binding.binding_ref
            or len(fact.request_fingerprint) != 64
            or fact.revision_ref != command.revision_ref
            or fact.tool_request_ref != command.tool_request_ref
            or fact.sequence != command.sequence
            or fact.termination is not WindowsExecutionTermination.EXITED
            or fact.exit_code != 0
            or not receipt.evidence_ref
            or not fact.admission_ref
        ):
            raise ContractError("exact acknowledged successful text command is required")
        request = self._approved_text.approved_request(
            binding=binding, command=command, receipt=receipt,
        )
        if request is None:
            return None
        # The body is produced from the real authorized file FIRST and only a
        # body that exists is declared: the reader renders a declaration as
        # "the text is still coming", so declaring a read that could not produce
        # a body (too large, not UTF-8, file gone) would leave the conversation
        # waiting on a result that will never arrive.
        result = self._approved_text.read_verified_text(
            request=request, binding=binding, command=command, receipt=receipt,
        )
        # Declare before the body travels, so the reader can answer "still
        # coming" instead of reconstructing a terminal-only message.
        self._publisher.declare_pending(
            binding_ref=binding.binding_ref,
            credential=credential,
            command_id=command.command_id,
            run_id=command.run_id,
            request_fingerprint=fact.request_fingerprint,
        )
        stored = self._publisher.deliver(
            binding_ref=binding.binding_ref, credential=credential, result=result,
        )
        return TrustedVerifiedTextDelivery(
            result=result, pending_declared=True, content_uploaded=True,
            content_receipt=dict(stored),
        )

    def replay(
        self,
        *,
        delivery: TrustedVerifiedTextDelivery,
        binding_ref: str,
        credential: bytes,
    ) -> dict[str, Any]:
        """Re-send the *same* result after a transport failure.

        Identical correlation and identical bytes: the task is not re-executed,
        the file is not re-read and no new command is generated.
        """
        if not isinstance(delivery, TrustedVerifiedTextDelivery):
            raise ContractError("canonical text delivery required for a replay")
        return self._publisher.replay(
            binding_ref=binding_ref, credential=credential, result=delivery.result,
        )


def compose_verified_text_delivery(
    *,
    device: Any,
    file_requests: Any,
    file_authorization_port: Any,
    config: OutboundTransportConfig,
    clock: Callable[[], datetime],
    transport: PinnedHttpsJsonRequestPort | None = None,
) -> ResidentVerifiedTextPublisher:
    """Explicit trusted Resident composition; no ambient switch.

    Accepts only a genuine Windows device and independently configured file
    authorization: neither a P01 process approval nor a browser login grants
    READ by itself, and no env var can name a file.
    """
    from .local_agent import LocalAgentDeviceProfile, LocalAgentPlatform

    if (
        not isinstance(device, LocalAgentDeviceProfile)
        or device.platform is not LocalAgentPlatform.WINDOWS
        or not callable(getattr(file_requests, "request_for_completed_command", None))
        or not callable(getattr(file_authorization_port, "authorize", None))
    ):
        raise ContractError("current P01 selected-root READ authorization required")
    producer = WindowsVerifiedTextProducer(
        files=WindowsSelectedRootFileRuntime(
            device=device, authorization_port=file_authorization_port,
        ),
        requests=file_requests,
        clock=clock,
    )
    return ResidentVerifiedTextPublisher(
        approved_text=producer,
        publisher=LocalAgentTextResultPublisher(
            transport=transport if transport is not None else StdlibPinnedHttpsJsonRequestPort(),
            config=config,
        ),
    )


PRODUCTION_VERIFIED_TEXT_PROVIDER_CONFIGURED = False
POST_ACK_ONLY = True
PENDING_BEFORE_BODY = True
SECOND_TXT_UPLOAD_PATH = False
TRUNCATION_AS_COMPLETENESS = False
GENERIC_STDOUT_TRUSTED = False
