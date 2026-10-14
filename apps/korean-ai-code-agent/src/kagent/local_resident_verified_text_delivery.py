"""#4139 — ordered Windows TXT READ → canonical verified text result.

This is the Resident-side producer for the one contract LOCAL1's #4705 broker
store accepts: a bounded UTF-8 body, correlated to the command that produced it,
on the one canonical device route. The *order* is the contract:

    pending declaration (ADMITTED, still unacknowledged)
      → that declaration was accepted by the broker
      → the approved real READ of the P01-authorized file runs, and its bytes
        are preserved in memory
      → the command's successful completion ACK is confirmed
      → those *same* preserved bytes travel as this command's text result

Nothing is re-read after the completion ACK, so a post-ACK file change can never
be presented as the result of the execution that was acknowledged, and a READ
that failed is never turned into a successful ACK: the read runs before the
acknowledgement, and if it cannot produce a bounded body the command is refused
(no ACK, no content) rather than acknowledged as if it had returned text.

Nothing new is minted:

* the **same** ``WindowsSelectedRootFileRuntime`` performs the read, so the
  **same** ``P01LocalPermissionWindowsFileAuthorizationPort`` re-checks the
  current P01 approval, local permission, selected root, symlink/reparse escape,
  allowed operation and file size before a single byte is read;
* the **same** deployment-injected trusted P01 source supplies the exact
  authorized READ for the admitted command — here pinned to a text file instead
  of a workbook, with its own one-shot plan/evidence queue;
* the **same** ``LocalAgentTextResultPublisher`` (pinned TLS, one route) sends
  the result. There is no second TXT upload path and no second file authority.

    PENDING_BEFORE_ACK=1 · READ_BEFORE_ACK=1 · READ_REUSED_NOT_REREAD=1
    UPLOAD_AFTER_ACK=1 · POST_ACK_ONLY=0 · SECOND_TXT_UPLOAD_PATH=0
    TRUNCATION_AS_COMPLETENESS=0 · GENERIC_STDOUT_TRUSTED=0

Contract junction (LOCAL1 #4705, revision ``a6c48989``): the broker write gate
now admits the ``pending`` state for an *ADMITTED* (not yet acknowledged) command,
which is what makes the order above expressible. A ``pending`` declaration that
the broker refuses stops the lane before the READ and before the successful
completion ACK.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from .contracts import ContractError
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
#: At most this many declared-but-not-yet-uploaded reads at once. The staging
#: map is bounded so a stream of admitted commands cannot grow it without limit.
MAX_PENDING_TEXT_READS = 8
_MAX_CLOCK_SKEW = timedelta(minutes=5)
#: The only file kind this lane may return as a text read. A text result is a
#: bounded read result, never a binary/document lane (that stays #3580 Office).
TEXT_READ_SUFFIX = ".txt"


def _ref(value: Any, field_name: str) -> str:
    if (
        type(value) is not str
        or not 0 < len(value) <= 512
        or any(character.isspace() for character in value)
    ):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ContractError(f"{field_name} must be lowercase SHA-256")
    return value


def _aware(value: Any, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ContractError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class AdmittedTextReadContext:
    """The admitted (unacknowledged) correlation this lane acts on.

    Produced by the resident host from the canonical coordinator's admitted
    hook — the same request id, command fingerprint and admission evidence the
    completion acknowledgement will later carry. It carries no file path and no
    approval: the P01 source supplies those.
    """

    admission_ref: str
    evidence_ref: str
    request_id: str
    command_fingerprint: str
    admitted_at: datetime

    def __post_init__(self) -> None:
        _ref(self.admission_ref, "admission_ref")
        _ref(self.evidence_ref, "evidence_ref")
        _ref(self.request_id, "request_id")
        _digest(self.command_fingerprint, "command_fingerprint")
        _aware(self.admitted_at, "admitted_at")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-admitted-text-read-context.v1",
            "request_id": self.request_id,
            "command_fingerprint": self.command_fingerprint,
            "admission_ref": self.admission_ref,
            "evidence_ref": self.evidence_ref,
            "admitted_at": self.admitted_at.isoformat().replace("+00:00", "Z"),
            "file_path_present": False,
            "approval_created": False,
        }


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

    def approved_plan_for_admitted_command(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        admitted: AdmittedTextReadContext,
    ) -> TrustedP01VerifiedTextFilePlan | None: ...


class TrustedP01VerifiedTextFilePlanBridge:
    """One-shot host adapter: the authorized text READ plus its P01 evidence.

    It answers *before* the completion acknowledgement, because that is when the
    pending declaration and the READ happen; the evidence it queues is consumed
    by the existing Windows file authorization port, which independently
    re-evaluates local policy and the P01 pause/decision at read time. Nothing
    here bypasses or replaces that port.
    """

    def __init__(self, *, source: TrustedP01VerifiedTextPlanSource) -> None:
        if not callable(getattr(source, "approved_plan_for_admitted_command", None)):
            raise ContractError("trusted P01 verified-text plan source required")
        self._source = source
        self._pending: dict[str, WindowsFileAuthorityEvidence] = {}
        self._consumed_commands: set[tuple[str, str]] = set()

    def request_for_admitted_command(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        admitted: AdmittedTextReadContext,
    ) -> LocalFileRequest | None:
        if (
            not isinstance(binding, DeviceBinding)
            or not isinstance(command, DeviceCommandEnvelope)
            or not isinstance(admitted, AdmittedTextReadContext)
        ):
            raise ContractError("canonical admitted P01 command required")
        if command.binding_ref != binding.binding_ref:
            raise ContractError("text command does not belong to this binding")
        key = (binding.binding_ref, command.command_id)
        if key in self._consumed_commands:
            raise ContractError("text command file plan already consumed")
        self._consumed_commands.add(key)
        plan = self._source.approved_plan_for_admitted_command(
            binding=binding, command=command, admitted=admitted,
        )
        if plan is None:
            return None
        if not isinstance(plan, TrustedP01VerifiedTextFilePlan):
            raise ContractError("text plan source returned invalid authority material")
        request, evidence = plan.file_request, plan.file_evidence
        now = admitted.admitted_at
        if (
            plan.binding_ref != binding.binding_ref
            or plan.command_id != command.command_id
            or plan.tool_request_ref != command.tool_request_ref
            or plan.run_id != command.run_id
            or plan.request_id != admitted.request_id
            or plan.revision_ref != command.revision_ref
            or plan.command_fingerprint != admitted.command_fingerprint
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
            "plan_resolved_before_ack": True,
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
        if not callable(getattr(requests, "request_for_admitted_command", None)):
            raise ContractError("trusted approved text READ request port required")
        if not callable(clock):
            raise ContractError("trusted pre-ACK local clock required")
        self._files = files
        self._requests = requests
        self._clock = clock

    def approved_request(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        admitted: AdmittedTextReadContext,
    ) -> LocalFileRequest | None:
        """The exact authorized READ for this admitted command, or None."""
        request = self._requests.request_for_admitted_command(
            binding=binding, command=command, admitted=admitted,
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
        admitted: AdmittedTextReadContext,
        now: datetime | None = None,
    ) -> VerifiedTextResult:
        """Perform the real P01-authorized READ and bound what came back."""
        moment = now if now is not None else self._clock()
        if (
            not isinstance(moment, datetime)
            or moment.tzinfo is None
            or moment.utcoffset() is None
            or moment < admitted.admitted_at - _MAX_CLOCK_SKEW
        ):
            raise ContractError("current trusted pre-ACK local file clock required")
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
                request_fingerprint=admitted.command_fingerprint,
                content=raw,
            )
        except VerifiedTextResultRefused as exc:
            # Too large or not UTF-8: refused, never truncated or transcoded.
            raise ContractError(f"verified text result refused: {exc}") from exc
        return built


@dataclass(frozen=True, slots=True)
class _PreservedTextRead:
    """An admitted command whose pending declaration was accepted."""

    request: LocalFileRequest
    admitted: AdmittedTextReadContext


@dataclass(frozen=True, slots=True)
class TrustedVerifiedTextDelivery:
    """What actually left this PC. Never the body, never a false completion."""

    result: VerifiedTextResult
    pending_declared: bool
    read_before_ack: bool
    content_uploaded: bool
    content_receipt: dict[str, Any]

    def __post_init__(self) -> None:
        if (
            self.content_uploaded is not True
            or self.pending_declared is not True
            or self.read_before_ack is not True
        ):
            raise ContractError(
                "a text delivery is only reported after an ordered pending, "
                "pre-acknowledgement read and stored body"
            )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-resident-verified-text-delivery.v1",
            "pending_declared": True,
            "pending_before_ack": True,
            "read_before_ack": True,
            "content_uploaded": True,
            "pending_before_body": True,
            "content_present": self.content_receipt.get("content_present") is True,
            "content_bytes": self.result.content_bytes,
            "content_sha256": self.result.content_sha256,
            "command_id": self.result.command_id,
            "run_id": self.result.run_id,
            "file_reread_after_ack": False,
            "returned_to_claw": True,
            "generic_stdout_trusted": False,
            "truncated_as_complete": False,
        }


class ResidentVerifiedTextPublisher:
    """The ordered sender for one P01-approved text read (#4139).

    Three steps, on the resident's existing admitted/executed/acknowledged
    call path:

    ``declare_pending_for_admitted`` (pre-execution, pre-ACK)
        register the pending state for this exact admitted command. A refusal
        here propagates: the command is neither executed nor acknowledged.

    ``observe_approved_read`` (post-execution, pre-ACK)
        run the approved real READ and preserve the bounded bytes. The bytes are
        held in memory, never written to disk, and never re-read later.

    ``on_acknowledged`` (post-ACK)
        confirm the successful completion acknowledgement and upload the
        *preserved* bytes on the one canonical route.
    """

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
        self._preserved: dict[tuple[str, str], _PreservedTextRead] = {}
        self._results: dict[tuple[str, str], VerifiedTextResult] = {}

    def _discard(self, key: tuple[str, str]) -> None:
        """Release a declared read that can never become an uploaded body."""
        self._preserved.pop(key, None)
        self._results.pop(key, None)

    def _key(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope
    ) -> tuple[str, str]:
        if not isinstance(binding, DeviceBinding) or not isinstance(
            command, DeviceCommandEnvelope
        ):
            raise ContractError("canonical binding/command required")
        if command.binding_ref != binding.binding_ref:
            raise ContractError("command does not belong to this binding")
        return (binding.binding_ref, command.command_id)

    def declare_pending_for_admitted(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        admitted: AdmittedTextReadContext,
        credential: bytes,
    ) -> bool:
        """Step 1: declare ``pending`` before the READ and before the ACK.

        Returns False when the admitted command is not an approved text READ at
        all. Any failure to declare raises, so the caller stops before the READ
        and before the completion acknowledgement.
        """
        if (
            not isinstance(admitted, AdmittedTextReadContext)
            or type(credential) is not bytes
            or not credential
        ):
            raise ContractError("canonical admitted correlation/credential required")
        key = self._key(binding=binding, command=command)
        request = self._approved_text.approved_request(
            binding=binding, command=command, admitted=admitted,
        )
        if request is None:
            return False
        if key in self._preserved:
            raise ContractError("text read already declared for this command")
        if len(self._preserved) >= MAX_PENDING_TEXT_READS:
            raise ContractError("too many declared text reads")
        # The declaration is confirmed by the broker *before* the READ runs, so
        # a refused declaration can never be followed by a read or by a
        # successful completion acknowledgement.
        self._publisher.declare_pending(
            binding_ref=binding.binding_ref,
            credential=credential,
            command_id=command.command_id,
            run_id=command.run_id,
            request_fingerprint=admitted.command_fingerprint,
        )
        self._preserved[key] = _PreservedTextRead(request=request, admitted=admitted)
        return True

    def observe_approved_read(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        execution: Any,
    ) -> VerifiedTextResult | None:
        """Step 2: read the approved file and preserve its bytes, pre-ACK.

        Returns None when this command never declared a pending text read, or
        when the execution itself did not succeed — in that case the command's
        acknowledgement still reports its real outcome and no content travels.
        """
        key = self._key(binding=binding, command=command)
        preserved = self._preserved.get(key)
        if preserved is None:
            return None
        execution_command_id = getattr(execution, "command_id", None)
        execution_run_id = getattr(execution, "run_id", None)
        if execution_command_id != command.command_id or execution_run_id != command.run_id:
            self._discard(key)
            raise ContractError("observed execution does not match the declared text read")
        if (
            getattr(execution, "termination", None) is not WindowsExecutionTermination.EXITED
            or getattr(execution, "exit_code", None) != 0
        ):
            # A command that did not exit successfully produces no text result:
            # it will never be acknowledged as a successful read either, so the
            # declaration cannot become a body and its slot is released instead
            # of holding the lane until the process restarts.
            self._discard(key)
            return None
        admitted = preserved.admitted
        if (
            getattr(execution, "request_id", None) != admitted.request_id
            or getattr(execution, "request_fingerprint", None) != admitted.command_fingerprint
            or getattr(execution, "revision_ref", None) != command.revision_ref
            or getattr(execution, "tool_request_ref", None) != command.tool_request_ref
            or getattr(execution, "sequence", None) != command.sequence
            or getattr(execution, "binding_ref", None) != binding.binding_ref
        ):
            # The command is never acknowledged, so it can never carry a body:
            # release the slot and fail closed with the correlation refusal.
            self._discard(key)
            raise ContractError("observed execution lost the admitted text correlation")
        try:
            result = self._approved_text.read_verified_text(
                request=preserved.request, binding=binding, command=command,
                admitted=admitted,
            )
        except Exception:
            # A read that could not produce a bounded body is not a text result
            # and the command is not acknowledged; only the declaration is left
            # behind, never a claimed one.
            self._discard(key)
            raise
        if (
            result.command_id != command.command_id
            or result.run_id != command.run_id
            or result.request_fingerprint != admitted.command_fingerprint
        ):
            raise ContractError("pre-acknowledgement text read lost its correlation")
        self._results[key] = result
        return result

    def on_acknowledged(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        receipt: Any,
        credential: bytes,
    ) -> TrustedVerifiedTextDelivery | None:
        """Step 3: confirm the success ACK and upload the *preserved* bytes."""
        if (
            not isinstance(binding, DeviceBinding)
            or not isinstance(command, DeviceCommandEnvelope)
            or type(credential) is not bytes
            or not credential
        ):
            raise ContractError("canonical broker receipt/binding required before text delivery")
        key = self._key(binding=binding, command=command)
        preserved = self._preserved.pop(key, None)
        result = self._results.pop(key, None)
        if preserved is None or result is None:
            # Not a text command, or nothing was read pre-ACK: no body is
            # uploaded and the file is never read here.
            return None
        fact = receipt.execution
        if (
            fact.command_id != command.command_id
            or fact.run_id != command.run_id
            or fact.binding_ref != binding.binding_ref
            or fact.request_id != preserved.admitted.request_id
            or fact.request_fingerprint != preserved.admitted.command_fingerprint
            or fact.revision_ref != command.revision_ref
            or fact.tool_request_ref != command.tool_request_ref
            or fact.sequence != command.sequence
            or fact.termination is not WindowsExecutionTermination.EXITED
            or fact.exit_code != 0
            or not receipt.evidence_ref
            or not fact.admission_ref
        ):
            raise ContractError("exact acknowledged successful text command is required")
        # The bytes travel exactly as they were read before the acknowledgement:
        # no re-read, no re-execution and no new correlation.
        stored = self._publisher.deliver(
            binding_ref=binding.binding_ref, credential=credential, result=result,
        )
        return TrustedVerifiedTextDelivery(
            result=result, pending_declared=True, read_before_ack=True,
            content_uploaded=True, content_receipt=dict(stored),
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

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-resident-verified-text-publisher.v1",
            "declared_pending_count": len(self._preserved),
            "preserved_result_count": len(self._results),
            "pending_before_read": True,
            "read_before_ack": True,
            "upload_after_ack": True,
            "file_reread_after_ack": False,
            "new_command_created": False,
            "second_upload_path": False,
        }


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
        or not callable(getattr(file_requests, "request_for_admitted_command", None))
        or not callable(getattr(file_requests, "resolve", None))
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
POST_ACK_ONLY = False
PENDING_BEFORE_ACK = True
READ_BEFORE_ACK = True
READ_REUSED_NOT_REREAD = True
UPLOAD_AFTER_ACK = True
SECOND_TXT_UPLOAD_PATH = False
TRUNCATION_AS_COMPLETENESS = False
GENERIC_STDOUT_TRUSTED = False
