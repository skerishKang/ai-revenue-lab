"""#4139 trial — the ordered Resident TXT lane over the private MeshCentral read.

This is the Resident-facing half that turns the merged private-read executor
(:mod:`kagent.local_agent_meshcentral_private_reader`) into the *ordered* lane
the canonical runtime host already calls, so the trial runs inside the existing
approved TXT read path rather than beside it:

    declare pending (pre-READ, pre-ACK)
      → the private MeshCentral READ runs and its bytes are preserved in memory
      → the command's successful completion ACK is confirmed
      → those *same* preserved bytes travel on the one canonical route

The approval material does not change: the admitted command still carries the
canonical Broker TXT approval receipt minted by the Chat worker, and this lane
accepts it only when it validates through the *same* closed validator the P01
lane uses (``validate_txt_approval_receipt``) and names exactly the single trial
target the deployment material holds. Nothing here mints an approval, accepts a
browser- or environment-named file for a request, or opens a second upload
path: the deployment names one ``(node_ref, file_path)`` pair and one canonical
``(root_ref, path_relative)`` pair, and every other TEXT receipt is refused.

The only swap against :class:`ResidentVerifiedTextPublisher` is the *executor*
of the approved READ: the private, official-MeshCtrl read over the dedicated
Cloudflare tunnel replaces the local selected-root runtime. The order contract,
the correlation checks, the one publisher and the one route are reused
unchanged. The operator credential for that private route comes from the
existing DPAPI-protected deployment secret at call time; no password is stored
in module state.

    PENDING_BEFORE_ACK=1 · READ_BEFORE_ACK=1 · UPLOAD_AFTER_ACK=1
    POST_ACK_ONLY=0 · READ_REUSED_NOT_REREAD=1 · SECOND_TXT_UPLOAD_PATH=0
    TRUNCATION_AS_COMPLETENESS=0 · GENERIC_STDOUT_TRUSTED=0
    OFFICIAL_MESHCTRL_CLIENT=1 · PUBLIC_INBOUND_PORT=0 · SECOND_PC_PROTOCOL=0
    DPAPI_IN_MODULE_STATE=0
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from .contracts import ContractError
from .local_agent_command_material import validate_txt_approval_receipt
from .local_agent_control_plane_https import (
    PinnedHttpsJsonRequestPort,
    StdlibPinnedHttpsJsonRequestPort,
)
from .local_agent_meshcentral_private_reader import (
    MeshCentralCliFileReadPort,
    MeshCentralFileReadPort,
    MeshCentralFileReadRequest,
    MeshCentralReadRefused,
    MeshCentralVerifiedTextReader,
)
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope
from .local_agent_secure_transport import OutboundTransportConfig
from .local_agent_verified_text_result import (
    LocalAgentTextResultPublisher,
    VerifiedTextResult,
)
from .local_resident_verified_text_delivery import (
    AdmittedTextReadContext,
    MAX_PENDING_TEXT_READS,
    TrustedVerifiedTextDelivery,
)
from .windows_local_executor import WindowsExecutionTermination

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_MAX_FILE_PATH_CHARS = 512
_MAX_PATH_RELATIVE_CHARS = 256
_TEXT_READ_SUFFIX = ".txt"
_MAX_CLOCK_SKEW = timedelta(minutes=5)

#: The deployment-material switch the Resident resolves to compose this lane.
#: It names the factory of the trial text material, never a file for a request.
MESHCENTRAL_TRIAL_NODE_REF_ENV = "PADIEM_MESH_TRIAL_NODE_REF"
MESHCENTRAL_TRIAL_FILE_PATH_ENV = "PADIEM_MESH_TRIAL_FILE_PATH"
MESHCENTRAL_TRIAL_ROOT_REF_ENV = "PADIEM_MESH_TRIAL_ROOT_REF"
MESHCENTRAL_TRIAL_PATH_RELATIVE_ENV = "PADIEM_MESH_TRIAL_PATH_RELATIVE"
MESHCENTRAL_MESHCTRL_JS_ENV = "PADIEM_MESHCTRL_JS"
MESHCENTRAL_LOGIN_USER_ENV = "PADIEM_MESHCTRL_LOGIN_USER"
MESHCENTRAL_PASSWORD_FILE_ENV = "PADIEM_MESH_TRIAL_PASSWORD_FILE"
MESHCENTRAL_WSS_URL_ENV = "PADIEM_MESH_TRIAL_WSS_URL"
MESHCENTRAL_WORK_DIR_ENV = "PADIEM_MESH_TRIAL_WORK_DIR"


def _token(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value


def _path_relative(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_PATH_RELATIVE_CHARS
        or any(ord(character) < 32 for character in value)
        or not value.lower().endswith(_TEXT_READ_SUFFIX)
    ):
        raise ContractError("path_relative must be a bounded relative .txt path")
    return value


@dataclass(frozen=True, slots=True)
class MeshCentralTrialTextTarget:
    """The one private read the deployment material authorizes for the trial.

    ``node_ref`` and ``file_path`` are the MeshCentral execution target; the
    canonical ``root_ref``/``path_relative`` pair is what the admitted Broker
    TXT receipt must name for this target to answer. All four values come from
    deployment material, never from a request.
    """

    node_ref: str
    file_path: str
    root_ref: str
    path_relative: str

    def __post_init__(self) -> None:
        try:
            MeshCentralFileReadRequest(
                node_ref=self.node_ref, file_path=self.file_path,
            )
        except ValueError as exc:
            raise ContractError("trial target is not a bounded private read") from exc
        _token(self.root_ref, "root_ref")
        _path_relative(self.path_relative)


class SingleFileMeshCentralTrialTargetSource:
    """The deployment's single trial file, selected by the canonical receipt.

    A command without TXT approval material is not a text read (``None`` keeps
    its ordinary execution path). A present receipt is validated through the
    closed canonical validator, must correlate to this exact admitted command,
    must still be valid at admission time, and must name exactly the deployment
    target — anything else fails closed instead of reading a foreign file.
    """

    def __init__(self, *, target: MeshCentralTrialTextTarget) -> None:
        if not isinstance(target, MeshCentralTrialTextTarget):
            raise ContractError("canonical single-file trial target required")
        self._target = target

    def target_for_admitted_command(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        admitted: AdmittedTextReadContext,
        receipt: Any | None = None,
    ) -> MeshCentralTrialTextTarget | None:
        if receipt is None:
            return None
        if (
            not isinstance(binding, DeviceBinding)
            or not isinstance(command, DeviceCommandEnvelope)
            or not isinstance(admitted, AdmittedTextReadContext)
        ):
            raise ContractError("canonical admitted Broker command required")
        if command.binding_ref != binding.binding_ref:
            raise ContractError("trial text command does not belong to this binding")
        try:
            validated = validate_txt_approval_receipt(receipt)
        except ContractError as exc:
            raise ContractError("TXT approval receipt rejected") from exc
        args = validated["exact_tool_arguments"]
        if (
            validated["command_id"] != command.command_id
            or validated["request_id"] != admitted.request_id
            or args["run_id"] != command.run_id
            or args["device_id"] != binding.device_id
        ):
            raise ContractError("TXT approval receipt does not belong to this command")
        now = admitted.admitted_at
        try:
            expires_at = datetime.fromisoformat(
                validated["expires_at"].replace("Z", "+00:00")
            )
            requested_at = datetime.fromisoformat(
                args["requested_at"].replace("Z", "+00:00")
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ContractError("TXT approval receipt carries unparseable time") from exc
        if (
            expires_at <= now - _MAX_CLOCK_SKEW
            or requested_at > now + _MAX_CLOCK_SKEW
        ):
            raise ContractError("trial TXT approval expired or not yet valid")
        if (
            args["root_ref"] != self._target.root_ref
            or args["path_relative"] != self._target.path_relative
        ):
            raise ContractError(
                "trial TXT receipt names a file outside the deployment trial target"
            )
        return self._target

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-single-file-meshcentral-trial-target.v1",
            "one_shot_within_lane": True,
            "request_named_file": False,
            "approval_created": False,
            "raw_file_bytes_stored": False,
        }


@dataclass(frozen=True, slots=True)
class _PreservedTrialRead:
    """An admitted trial command whose pending declaration was accepted."""

    target: MeshCentralTrialTextTarget
    admitted: AdmittedTextReadContext


class MeshCentralResidentTextLane:
    """The host-facing ordered lane: same order, same publisher, one swap.

    The three methods are exactly the ones :class:`LocalAgentResidentRuntimeHost`
    calls on ``verified_text_lane``, with the same correlation and ordering
    checks as :class:`ResidentVerifiedTextPublisher`; only the approved READ is
    delegated to the private MeshCentral reader.
    """

    def __init__(
        self,
        *,
        source: Any,
        reader: MeshCentralVerifiedTextReader,
    ) -> None:
        if not callable(getattr(source, "target_for_admitted_command", None)):
            raise ContractError("trusted private MeshCentral trial text source required")
        if not isinstance(reader, MeshCentralVerifiedTextReader):
            raise ContractError("canonical private MeshCentral verified text reader required")
        self._source = source
        self._reader = reader
        self._preserved: dict[tuple[str, str], _PreservedTrialRead] = {}
        self._results: dict[tuple[str, str], VerifiedTextResult] = {}
        self._consumed: set[tuple[str, str]] = set()

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
        receipt: Any | None = None,
    ) -> bool:
        """Step 1: declare ``pending`` before the private READ and the ACK.

        Returns False when the admitted command is not a trial text READ at all.
        Any failure to declare raises, so the caller stops before the READ and
        before the completion acknowledgement.
        """
        if (
            not isinstance(admitted, AdmittedTextReadContext)
            or type(credential) is not bytes
            or not credential
        ):
            raise ContractError("canonical admitted correlation/credential required")
        key = self._key(binding=binding, command=command)
        if key in self._consumed:
            raise ContractError("trial text command target already consumed")
        target = self._source.target_for_admitted_command(
            binding=binding, command=command, admitted=admitted, receipt=receipt,
        )
        if target is None:
            return False
        if not isinstance(target, MeshCentralTrialTextTarget):
            raise ContractError("trial target source returned invalid material")
        self._consumed.add(key)
        if key in self._preserved:
            raise ContractError("text read already declared for this command")
        if len(self._preserved) >= MAX_PENDING_TEXT_READS:
            raise ContractError("too many declared text reads")
        # The declaration is confirmed by the broker *before* the READ runs, so
        # a refused declaration can never be followed by a read or by a
        # successful completion acknowledgement.
        self._reader.declare_pending(
            binding_ref=binding.binding_ref,
            credential=credential,
            command_id=command.command_id,
            run_id=command.run_id,
            request_fingerprint=admitted.command_fingerprint,
        )
        self._preserved[key] = _PreservedTrialRead(target=target, admitted=admitted)
        return True

    def observe_approved_read(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        execution: Any,
    ) -> VerifiedTextResult | None:
        """Step 2: run the private READ and preserve its bytes, pre-ACK.

        Returns None when this command never declared a pending trial read, or
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
            # its declaration cannot become a body and its slot is released.
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
            self._discard(key)
            raise ContractError("observed execution lost the admitted text correlation")
        try:
            result = self._reader.read_verified_result(
                command_id=command.command_id,
                run_id=command.run_id,
                request_fingerprint=admitted.command_fingerprint,
                node_ref=preserved.target.node_ref,
                file_path=preserved.target.file_path,
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
            # Not a trial text command, or nothing was read pre-ACK: no body is
            # uploaded and the target is never read here.
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
        stored = self._reader.deliver(
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

        Identical correlation and identical bytes: the command is not
        re-executed, the private file is not re-read and no new command is
        generated.
        """
        if not isinstance(delivery, TrustedVerifiedTextDelivery):
            raise ContractError("canonical text delivery required for a replay")
        return self._reader.replay(
            binding_ref=binding_ref, credential=credential, result=delivery.result,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-resident-meshcentral-text-lane.v1",
            "declared_pending_count": len(self._preserved),
            "preserved_result_count": len(self._results),
            "pending_before_read": True,
            "read_before_ack": True,
            "upload_after_ack": True,
            "file_reread_after_ack": False,
            "new_command_created": False,
            "second_upload_path": False,
        }


def _default_command_runner(argv: list[str], *, input: str, timeout: int) -> Any:
    """Run the official MeshCtrl child without leaking output or the secret."""

    return subprocess.run(
        argv, input=input.encode("utf-8"), capture_output=True, timeout=timeout,
    )


def _dpapi_password_provider(blob_path: str) -> Callable[[], str]:
    """Decrypt the operator credential from its DPAPI blob at call time only.

    The blob file holds the hex encoding of the DPAPI-protected credential, as
    written by the deployment. Decryption uses only the ``System.Security``
    assembly that ships with Windows: the PowerShell ``Security`` module is
    deliberately *not* used, because under the stock ``-NoProfile
    -NonInteractive`` host its autoload/import fails (module resolution, then a
    type-table collision). The plaintext crosses the process boundary as
    base64, so no console code page can mangle it; decoding happens here.
    """

    if not isinstance(blob_path, str) or not blob_path.strip():
        raise ContractError("the protected operator credential location is required")
    if not os.path.isfile(blob_path):
        raise ContractError("the protected operator credential file is missing")
    literal_path = os.path.abspath(blob_path).replace("'", "''")
    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Security;"
        f"$h=(Get-Content -LiteralPath '{literal_path}' -Raw).Trim();"
        "$n=$h.Length/2;$b=New-Object byte[] $n;"
        "for($i=0;$i -lt $n;$i++){$b[$i]=[Convert]::ToByte($h.Substring($i*2,2),16)};"
        "$p=[Security.Cryptography.ProtectedData]::Unprotect("
        "$b,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser);"
        "[Convert]::ToBase64String($p)"
    )

    def provider() -> str:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=60,
        )
        if getattr(completed, "returncode", None) != 0:
            raise MeshCentralReadRefused(
                "the protected operator credential could not be decrypted"
            )
        try:
            password = base64.b64decode(
                completed.stdout.strip(), validate=True
            ).decode("utf-16-le")
        except (ValueError, UnicodeDecodeError) as exc:
            raise MeshCentralReadRefused(
                "the protected operator credential could not be decoded"
            ) from exc
        return password.rstrip("\r\n")

    return provider


class MeshCentralTrialTextMaterial:
    """Deployment material: one trial target plus the private read port.

    The port decrypts the operator credential at read time; module state holds
    the *location* of the DPAPI blob, never the password.
    """

    def __init__(
        self,
        *,
        node_ref: str,
        file_path: str,
        root_ref: str,
        path_relative: str,
        meshctrl_js: str,
        login_user: str,
        password_provider: Callable[[], str],
        url: str = "wss://127.0.0.1:4443",
        work_dir: str | None = None,
        command_runner: Callable[..., Any] | None = None,
    ) -> None:
        target = MeshCentralTrialTextTarget(
            node_ref=node_ref, file_path=file_path,
            root_ref=root_ref, path_relative=path_relative,
        )
        self._source = SingleFileMeshCentralTrialTargetSource(target=target)
        self._port: MeshCentralFileReadPort = MeshCentralCliFileReadPort(
            command_runner=command_runner or _default_command_runner,
            meshctrl_js=meshctrl_js,
            login_user=login_user,
            password_provider=password_provider,
            url=url,
            work_dir=work_dir,
        )

    def target_for_admitted_command(
        self,
        *,
        binding: DeviceBinding,
        command: DeviceCommandEnvelope,
        admitted: AdmittedTextReadContext,
        receipt: Any | None = None,
    ) -> MeshCentralTrialTextTarget | None:
        return self._source.target_for_admitted_command(
            binding=binding, command=command, admitted=admitted, receipt=receipt,
        )

    def read_port(self) -> MeshCentralFileReadPort:
        return self._port


def make_meshcentral_trial_text_material() -> MeshCentralTrialTextMaterial:
    """Resident factory for the deployment's private trial text material.

    Reads only deployment configuration (the single trial target, the official
    client path, the operator identity and the DPAPI blob location). No request
    value and no environment value can name a file for a request: the target is
    fixed here, and a receipt for any other file is refused downstream.
    """

    def required(name: str) -> str:
        value = os.environ.get(name, "").strip()
        if not value:
            raise ValueError(f"{name} is required for the trial text material")
        return value

    password_file = required(MESHCENTRAL_PASSWORD_FILE_ENV)
    if not os.path.isfile(password_file):
        raise ValueError("the protected operator credential file is missing")
    return MeshCentralTrialTextMaterial(
        node_ref=required(MESHCENTRAL_TRIAL_NODE_REF_ENV),
        file_path=required(MESHCENTRAL_TRIAL_FILE_PATH_ENV),
        root_ref=required(MESHCENTRAL_TRIAL_ROOT_REF_ENV),
        path_relative=required(MESHCENTRAL_TRIAL_PATH_RELATIVE_ENV),
        meshctrl_js=required(MESHCENTRAL_MESHCTRL_JS_ENV),
        login_user=required(MESHCENTRAL_LOGIN_USER_ENV),
        password_provider=_dpapi_password_provider(password_file),
        url=os.environ.get(MESHCENTRAL_WSS_URL_ENV, "").strip()
        or "wss://127.0.0.1:4443",
        work_dir=os.environ.get(MESHCENTRAL_WORK_DIR_ENV, "").strip() or None,
    )


def compose_meshcentral_verified_text_delivery(
    *,
    material: Any,
    config: OutboundTransportConfig,
    transport: PinnedHttpsJsonRequestPort | None = None,
) -> MeshCentralResidentTextLane:
    """Explicit trial Resident composition; no ambient switch.

    Accepts only deployment material exposing one trial target source and one
    private read port; the one canonical text publisher and one route are the
    same ones the P01 lane uses.
    """

    if (
        not callable(getattr(material, "target_for_admitted_command", None))
        or not callable(getattr(material, "read_port", None))
    ):
        raise ContractError("trusted private MeshCentral trial text material required")
    reader = MeshCentralVerifiedTextReader(
        publisher=LocalAgentTextResultPublisher(
            transport=transport if transport is not None else StdlibPinnedHttpsJsonRequestPort(),
            config=config,
        ),
        port=material.read_port(),
    )
    return MeshCentralResidentTextLane(source=material, reader=reader)


__all__ = [
    "MESHCENTRAL_LOGIN_USER_ENV",
    "MESHCENTRAL_MESHCTRL_JS_ENV",
    "MESHCENTRAL_PASSWORD_FILE_ENV",
    "MESHCENTRAL_TRIAL_FILE_PATH_ENV",
    "MESHCENTRAL_TRIAL_NODE_REF_ENV",
    "MESHCENTRAL_TRIAL_PATH_RELATIVE_ENV",
    "MESHCENTRAL_TRIAL_ROOT_REF_ENV",
    "MESHCENTRAL_WORK_DIR_ENV",
    "MESHCENTRAL_WSS_URL_ENV",
    "MeshCentralResidentTextLane",
    "MeshCentralTrialTextMaterial",
    "MeshCentralTrialTextTarget",
    "SingleFileMeshCentralTrialTargetSource",
    "compose_meshcentral_verified_text_delivery",
    "make_meshcentral_trial_text_material",
]

PENDING_BEFORE_ACK = True
READ_BEFORE_ACK = True
UPLOAD_AFTER_ACK = True
POST_ACK_ONLY = False
READ_REUSED_NOT_REREAD = True
SECOND_TXT_UPLOAD_PATH = False
TRUNCATION_AS_COMPLETENESS = False
GENERIC_STDOUT_TRUSTED = False
OFFICIAL_MESHCTRL_CLIENT = True
PUBLIC_INBOUND_PORT = False
SECOND_PC_PROTOCOL = False
DPAPI_IN_MODULE_STATE = False
