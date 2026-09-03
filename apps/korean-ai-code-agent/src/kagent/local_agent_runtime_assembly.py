from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
from typing import Any, Protocol

from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile, LocalCommandRequest
from .local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from .local_agent_permissions import DevicePermissionProfile
from .local_agent_secure_channel import PinnedOutboundBrokerBinding
from .windows_local_executor import (
    WindowsExecutionReceipt,
    WindowsExecutionTermination,
    command_request_fingerprint,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class WindowsReceiptRuntimePort(Protocol):
    def execute_with_receipt(self, request: LocalCommandRequest, *, now: datetime) -> WindowsExecutionReceipt:
        ...

    def cancel(self, request_id: str) -> None:
        ...


@dataclass(frozen=True, slots=True)
class LocalAgentRuntimeAssemblyReceipt:
    assembly_ref: str
    binding_ref: str
    session_id: str
    request_id: str
    run_id: str
    device_id: str
    workspace_ref: str
    root_ref: str
    request_fingerprint: str
    termination: WindowsExecutionTermination
    executable_profile_ref: str
    authorization_ref: str
    started_at: datetime
    ended_at: datetime
    exit_code: int | None
    dirty_worktree_before: bool
    dirty_worktree_after: bool
    stdout_chars: int
    stderr_chars: int

    def __post_init__(self) -> None:
        for field_name in (
            "assembly_ref",
            "binding_ref",
            "session_id",
            "request_id",
            "run_id",
            "device_id",
            "workspace_ref",
            "root_ref",
            "executable_profile_ref",
            "authorization_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        fingerprint = self.request_fingerprint.strip().lower() if isinstance(self.request_fingerprint, str) else ""
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ContractError("request_fingerprint must be a lowercase SHA-256 digest")
        object.__setattr__(self, "request_fingerprint", fingerprint)
        if not isinstance(self.termination, WindowsExecutionTermination):
            try:
                object.__setattr__(self, "termination", WindowsExecutionTermination(self.termination))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid execution termination") from exc
        started = _aware(self.started_at, "started_at")
        ended = _aware(self.ended_at, "ended_at")
        if ended < started:
            raise ContractError("ended_at cannot precede started_at")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "ended_at", ended)
        if self.exit_code is not None and (isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)):
            raise ContractError("exit_code must be an integer or None")
        if not isinstance(self.dirty_worktree_before, bool) or not isinstance(self.dirty_worktree_after, bool):
            raise ContractError("dirty-worktree flags must be boolean")
        for field_name in ("stdout_chars", "stderr_chars"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractError(f"{field_name} must be a non-negative integer")

    @classmethod
    def from_windows_receipt(
        cls,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        workspace_ref: str,
        request: LocalCommandRequest,
        receipt: WindowsExecutionReceipt,
    ) -> "LocalAgentRuntimeAssemblyReceipt":
        if not isinstance(receipt, WindowsExecutionReceipt):
            raise ContractError("runtime must return WindowsExecutionReceipt")
        result = receipt.result
        expected = (request.request_id, request.run_id, request.device_id, request.root_ref)
        actual = (result.request_id, result.run_id, result.device_id, result.root_ref)
        if actual != expected:
            raise ContractError("Windows execution receipt correlation mismatch")
        fingerprint = command_request_fingerprint(request)
        payload = {
            "binding_ref": binding.binding_ref,
            "session_id": session.session_id,
            "request_fingerprint": fingerprint,
            "authorization_ref": receipt.authorization_ref,
            "termination": receipt.termination.value,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return cls(
            assembly_ref=f"local_assembly_{hashlib.sha256(encoded).hexdigest()[:24]}",
            binding_ref=binding.binding_ref,
            session_id=session.session_id,
            request_id=request.request_id,
            run_id=request.run_id,
            device_id=request.device_id,
            workspace_ref=workspace_ref,
            root_ref=request.root_ref,
            request_fingerprint=fingerprint,
            termination=receipt.termination,
            executable_profile_ref=receipt.executable_profile_ref,
            authorization_ref=receipt.authorization_ref,
            started_at=result.started_at,
            ended_at=result.ended_at,
            exit_code=result.exit_code,
            dirty_worktree_before=result.dirty_worktree_before,
            dirty_worktree_after=result.dirty_worktree_after,
            stdout_chars=len(result.stdout),
            stderr_chars=len(result.stderr),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-local-agent-runtime-assembly-receipt.v1",
            "assembly_ref": self.assembly_ref,
            "binding_ref": self.binding_ref,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "workspace_ref": self.workspace_ref,
            "root_ref": self.root_ref,
            "request_fingerprint": self.request_fingerprint,
            "termination": self.termination.value,
            "executable_profile_ref": self.executable_profile_ref,
            "authorization_ref": self.authorization_ref,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "ended_at": self.ended_at.isoformat().replace("+00:00", "Z"),
            "exit_code": self.exit_code,
            "dirty_worktree_before": self.dirty_worktree_before,
            "dirty_worktree_after": self.dirty_worktree_after,
            "stdout_chars": self.stdout_chars,
            "stderr_chars": self.stderr_chars,
            "raw_argv": False,
            "stdout": False,
            "stderr": False,
            "raw_device_credential": False,
            "broker_payload": False,
            "client_execution_authority": False,
        }


class BoundLocalAgentRuntimeAssembly:
    """Correlate current Local Agent identity/session state before delegated Windows execution.

    Broker command admission/replay remains #1634. P01/local permission authority
    and subprocess execution remain in the existing Windows runtime stack.
    """

    def __init__(
        self,
        *,
        device: LocalAgentDeviceProfile,
        binding: DeviceBinding,
        permissions: DevicePermissionProfile,
        broker_authority: PinnedOutboundBrokerBinding,
        runtime: WindowsReceiptRuntimePort,
    ) -> None:
        if not isinstance(device, LocalAgentDeviceProfile):
            raise ContractError("device must be LocalAgentDeviceProfile")
        if not isinstance(binding, DeviceBinding):
            raise ContractError("binding must be DeviceBinding")
        if not isinstance(permissions, DevicePermissionProfile):
            raise ContractError("permissions must be DevicePermissionProfile")
        if not isinstance(broker_authority, PinnedOutboundBrokerBinding):
            raise ContractError("broker_authority must be PinnedOutboundBrokerBinding")
        if not hasattr(runtime, "execute_with_receipt") or not hasattr(runtime, "cancel"):
            raise ContractError("runtime must support execute_with_receipt and cancel")
        if binding.device_id != device.device_id or permissions.device_id != device.device_id:
            raise ContractError("Local Agent assembly device correlation mismatch")
        if binding.workspace_ref != device.workspace_ref or permissions.workspace_ref != device.workspace_ref:
            raise ContractError("Local Agent assembly workspace correlation mismatch")
        device_roots = {item.root_ref for item in device.roots}
        permission_roots = {item.root_ref for item in permissions.roots}
        if device_roots != permission_roots:
            raise ContractError("permission roots must exactly match current selected device roots")
        if (
            broker_authority.binding_ref != binding.binding_ref
            or broker_authority.device_id != binding.device_id
            or broker_authority.account_ref != binding.account_ref
            or broker_authority.workspace_ref != binding.workspace_ref
            or broker_authority.credential_generation != binding.credential_generation
        ):
            raise ContractError("pinned broker authority does not match current device binding")
        self._device = device
        self._binding = binding
        self._permissions = permissions
        self._broker_authority = broker_authority
        self._runtime = runtime
        self._active_owners: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def workspace_ref(self) -> str:
        return self._device.workspace_ref

    def _require_context(self, *, session: DeviceSession, now: datetime) -> None:
        now = _aware(now, "now")
        if self._binding.state is not DeviceLifecycle.ONLINE:
            raise ContractError("Local Agent binding must be ONLINE to execute")
        self._broker_authority.require_current_binding(self._binding, now=now)
        self._broker_authority.require_session(session, now=now)

    def execute(
        self,
        *,
        session: DeviceSession,
        request: LocalCommandRequest,
        now: datetime,
    ) -> LocalAgentRuntimeAssemblyReceipt:
        if not isinstance(session, DeviceSession):
            raise ContractError("session must be DeviceSession")
        if not isinstance(request, LocalCommandRequest):
            raise ContractError("request must be LocalCommandRequest")
        now = _aware(now, "now")
        self._require_context(session=session, now=now)
        if request.device_id != self._device.device_id:
            raise ContractError("local command request device mismatch")
        self._device.root(request.root_ref)
        self._permissions.root_policy(request.root_ref)
        if request.requested_at > now:
            raise ContractError("local command request cannot be from the future")
        with self._lock:
            if request.request_id in self._active_owners:
                raise ContractError("local command request is already active in this assembly")
            self._active_owners[request.request_id] = session.session_id
        try:
            receipt = self._runtime.execute_with_receipt(request, now=now)
        finally:
            with self._lock:
                self._active_owners.pop(request.request_id, None)
        return LocalAgentRuntimeAssemblyReceipt.from_windows_receipt(
            binding=self._binding,
            session=session,
            workspace_ref=self._device.workspace_ref,
            request=request,
            receipt=receipt,
        )

    def cancel(
        self,
        *,
        session: DeviceSession,
        request_id: str,
        now: datetime,
    ) -> None:
        request_id = _ref(request_id, "request_id")
        self._require_context(session=session, now=now)
        with self._lock:
            owner = self._active_owners.get(request_id)
            if owner is None:
                raise ContractError("Local Agent assembly does not own an active request with this id")
            if owner != session.session_id:
                raise ContractError("active Local Agent request belongs to a different device session")
        self._runtime.cancel(request_id)

    def safe_dict(self, *, now: datetime) -> dict[str, Any]:
        now = _aware(now, "now")
        current = True
        reason = None
        try:
            if self._binding.state is not DeviceLifecycle.ONLINE:
                raise ContractError("binding lifecycle is not ONLINE")
            self._broker_authority.require_current_binding(self._binding, now=now)
        except ContractError as exc:
            current = False
            reason = str(exc)
        return {
            "contract_version": "claw-local-agent-runtime-assembly.v1",
            "device_id": self._device.device_id,
            "workspace_ref": self._device.workspace_ref,
            "binding_ref": self._binding.binding_ref,
            "binding_state": self._binding.state.value,
            "credential_generation": self._binding.credential_generation,
            "selected_root_refs": sorted(item.root_ref for item in self._device.roots),
            "permission_root_refs": sorted(item.root_ref for item in self._permissions.roots),
            "broker_config_fingerprint": self._broker_authority.config_fingerprint,
            "current": current,
            "blocked_reason": reason,
            "online_required": True,
            "p01_authorization_reused": True,
            "windows_executor_reused": True,
            "broker_wire_protocol_defined": False,
            "replay_model_duplicated": False,
            "raw_device_credential": False,
            "client_execution_authority": False,
            "real_remote_broker": False,
            "production_ready": False,
        }


ONE_LOCAL_AGENT_RUNTIME_ASSEMBLY = True
ONLINE_BINDING_REQUIRED = True
BROKER_WIRE_PROTOCOL_INVENTED = False
REPLAY_MODEL_DUPLICATED = False
RAW_CREDENTIAL_IN_ASSEMBLY_RECEIPT = False
RAW_ARGV_IN_ASSEMBLY_RECEIPT = False
RAW_STDOUT_STDERR_IN_ASSEMBLY_RECEIPT = False
REAL_REMOTE_BROKER_CONFIGURED = False
REAL_REMOTE_CONTROL_CONFIGURED = False
PRODUCTION_READY = False
