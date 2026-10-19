"""#5015: one server-verified PC work context for Chat and Claw model calls.

Two *different* authoritative sources answer two different questions, and the
context keeps them separate instead of collapsing them:

* the canonical Broker device directory (#4418) answers "what does this account
  have registered/online, and what would the UI show?";
* the deployment-owned Mesh ownership map answers "which PC may this verified
  connector account actually execute on?".

An empty Broker list therefore never demotes a working Mesh target to
"unregistered", and an online Broker badge never grants tool permission. The
context is a per-request observation, not an execution grant: every tool
dispatch still re-verifies the owner and the exact target at execution time.

A new conversation sees the account's current state because both reads happen
on the request, not from browser memory or a fixed "always connected" prompt.
No idle polling is added: one request makes at most one read of each authority.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

PC_WORK_CONTEXT_VERSION = "padiem-pc-work-context.v1"
PC_DRIVE_TOOL_ID = "claw.pc.query_drives"
PC_LIST_FILES_TOOL_ID = "claw.pc.list_files"
PC_READ_FILE_TOOL_ID = "claw.pc.read_file"
PC_DRIVE_TOOL_CAPABILITY = "읽기 전용 파일 시스템 드라이브 목록"
PC_TOOL_SUMMARY = (
    f"{PC_DRIVE_TOOL_ID} (드라이브 목록), {PC_LIST_FILES_TOOL_ID} "
    f"(승인된 폴더 목록), {PC_READ_FILE_TOOL_ID} (UTF-8 텍스트 파일 읽기)"
)
MAX_RENDERED_CHARS = 1800
MAX_DEVICE_NAME_CHARS = 60
_MAX_RENDERED_DEVICES = 6
_DEVICE_LIMIT = 24
_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
#: Same closed grammar the Mesh ownership map accepts for device/node refs.
_EXEC_REF_PATTERN = re.compile(r"^[A-Za-z0-9_.:@+\-\\/]{1,1024}$")
_STATES = ("CONNECTED", "OFFLINE", "REVOKED")
_MESH_EXECUTION_MODE = "mesh"

# Broker directory status
_READY = "ready"
_NO_DEVICE = "no_device"
_OFFLINE = "offline"
_PAUSED = "paused"
_UNCONFIGURED = "unconfigured"
_READ_FAILED = "read_failed"
_UNVERIFIED_OWNER = "unverified_owner"

# Mesh execution-target status
_EXEC_READY = "ready"
_EXEC_UNCONFIGURED = "unconfigured"
_EXEC_OWNER_UNAVAILABLE = "owner_unavailable"
_EXEC_NO_TARGET = "no_target"

# Broker-device <-> Mesh-target correspondence
_MAPPING_CONFIRMED = "confirmed"
_MAPPING_UNMAPPED = "unmapped"
_MAPPING_IDENTITY_UNCONFIRMED = "identity_unconfirmed"
_MAPPING_MISMATCH = "mismatch"
_MAPPING_UNKNOWN = "unknown"

# Canonical connector owner scope (B54 session -> CP connector context)
_PC_SCOPE_READY = "ready"
_PC_SCOPE_OWNER_UNAVAILABLE = "owner_unavailable"
PC_SCOPE_OWNER_UNAVAILABLE = _PC_SCOPE_OWNER_UNAVAILABLE


@dataclass(frozen=True, slots=True)
class PcConnectorScope:
    status: str
    account_ref: str | None = None
    workspace_ref: str | None = None
    session_id: str | None = None

    @property
    def ready(self) -> bool:
        return self.status == _PC_SCOPE_READY

# Saved target preference read status
SAVED_SELECTION_NONE = "none"
SAVED_SELECTION_SELECTED = "selected"
SAVED_SELECTION_UNCONFIGURED = "unconfigured"
SAVED_SELECTION_UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SavedDeviceSelection:
    status: str
    device_id: str | None = None


@dataclass(frozen=True, slots=True)
class PcWorkDevice:
    device_id: str
    name: str | None
    state: str
    usable: bool


@dataclass(frozen=True, slots=True)
class PcExecutionTarget:
    """One verified Mesh command target; never chosen by the browser."""

    status: str
    device_id: str | None = None
    pinned: bool = False

    @property
    def ready(self) -> bool:
        return self.status == _EXEC_READY


@dataclass(frozen=True, slots=True)
class PcWorkContext:
    broker_status: str
    devices: tuple[PcWorkDevice, ...] = ()
    broker_target_device_id: str | None = None
    execution: PcExecutionTarget = PcExecutionTarget(status=_EXEC_UNCONFIGURED)
    mapping: str = _MAPPING_UNKNOWN
    selected_device_id: str | None = None
    saved_selection_status: str = SAVED_SELECTION_NONE

    @property
    def verified(self) -> bool:
        return self.broker_status in (_READY, _NO_DEVICE, _OFFLINE, _PAUSED)

    @property
    def usable_count(self) -> int:
        return sum(1 for device in self.devices if device.usable)

    @property
    def status(self) -> str:
        """Compatibility alias for the Broker directory status."""
        return self.broker_status

    @property
    def target_device_id(self) -> str | None:
        """Compatibility alias for the single usable Broker device hint."""
        return self.broker_target_device_id

    @property
    def execution_device_id(self) -> str | None:
        return self.execution.device_id if self.execution.ready else None

    @property
    def selected_confirmed(self) -> bool:
        """True when no device was selected, or the selection == the target."""
        return self.selected_device_id is None or self.mapping == _MAPPING_CONFIRMED

    @property
    def tool_available(self) -> bool:
        return (
            self.execution.ready
            and self.saved_selection_status != SAVED_SELECTION_UNAVAILABLE
            and self.broker_status != _PAUSED
            and self.mapping in (
                _MAPPING_CONFIRMED, _MAPPING_UNMAPPED, _MAPPING_IDENTITY_UNCONFIRMED,
            )
        )


def _clean_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable() and ch not in "\r\n\t")
    cleaned = cleaned.strip()
    return cleaned[:MAX_DEVICE_NAME_CHARS] or None


def _device_label(device: PcWorkDevice) -> str:
    return device.name or device.device_id


def _state_label(device: PcWorkDevice) -> str:
    if device.state == "CONNECTED" and device.usable:
        return "온라인"
    if device.state == "REVOKED":
        return "연결 해제"
    return "오프라인"


def _safe_exec_ref(value: Any) -> str | None:
    if not isinstance(value, str) or not _EXEC_REF_PATTERN.fullmatch(value):
        return None
    return value


async def _resolve_owner_session(
    request: Any, owner_id: str,
) -> tuple[str | None, Any | None]:
    """Same fail-closed rules as ``_resolve_memory_workspace``, plus the session.

    Both identity components absent keeps the historical ``owner:<id>``
    compatibility namespace (no canonical session). Partial configuration or a
    failed/inactive session yields no workspace, never a fallback identity.
    """
    state = getattr(getattr(request, "app", None), "state", None)
    shadow_store = getattr(state, "identity_shadow_store", None)
    authority = getattr(state, "control_plane_identity_authority", None)
    if shadow_store is None and authority is None:
        return f"owner:{owner_id}", None
    if shadow_store is None or authority is None:
        return None, None
    from .control_plane_identity_shadow import resolve_refreshed_session

    try:
        session = await resolve_refreshed_session(
            authority=authority, store=shadow_store, product_user_id=owner_id,
        )
    except Exception:
        return None, None
    workspace = getattr(session, "tenant_id", None)
    if not isinstance(workspace, str) or not workspace.strip():
        return None, None
    return workspace, session


async def _resolve_execution_target(
    request: Any, *, session_id: str | None, selected_device_id: str | None,
    account_ref: str | None = None,
) -> PcExecutionTarget:
    """Resolve the deployment's single command-capable Mesh target.

    The optional selected device only narrows the existing map; it can never
    introduce a target. No target, an unconfigured Mesh lane and an unresolvable
    connector owner all stay distinct so callers can report the exact reason.
    """
    state = getattr(getattr(request, "app", None), "state", None)
    mesh_source = getattr(state, "oracle_mesh_return_source", None)
    if getattr(mesh_source, "configured", False) is not True:
        return PcExecutionTarget(status=_EXEC_UNCONFIGURED)
    if getattr(mesh_source, "execution_mode", None) != _MESH_EXECUTION_MODE:
        return PcExecutionTarget(status=_EXEC_UNCONFIGURED)
    command_target = getattr(mesh_source, "command_target", None)
    if not callable(command_target):
        return PcExecutionTarget(status=_EXEC_OWNER_UNAVAILABLE)
    if account_ref is None:
        identity = getattr(state, "control_plane_identity_authority", None)
        scope_port = getattr(identity, "resolve_connector_owner_scope", None)
        if (
            not isinstance(session_id, str) or not session_id
            or not callable(scope_port)
        ):
            return PcExecutionTarget(status=_EXEC_OWNER_UNAVAILABLE)
        try:
            scope = scope_port(session_id=session_id)
            if inspect.isawaitable(scope):
                scope = await scope
        except Exception:
            return PcExecutionTarget(status=_EXEC_OWNER_UNAVAILABLE)
        account_ref = scope.get("account_ref") if isinstance(scope, Mapping) else None
    if not isinstance(account_ref, str) or not account_ref:
        return PcExecutionTarget(status=_EXEC_OWNER_UNAVAILABLE)
    try:
        target = command_target(
            account_ref=account_ref, device_id=selected_device_id,
        )
    except Exception:
        return PcExecutionTarget(status=_EXEC_NO_TARGET)
    if not isinstance(target, Mapping):
        return PcExecutionTarget(status=_EXEC_NO_TARGET)
    pinned_raw = target.get("device_id")
    pinned = _safe_exec_ref(pinned_raw) if pinned_raw is not None else None
    if pinned_raw is not None and pinned is None:
        return PcExecutionTarget(status=_EXEC_NO_TARGET)
    canonical = pinned or _safe_exec_ref(target.get("node_ref"))
    if canonical is None:
        return PcExecutionTarget(status=_EXEC_NO_TARGET)
    return PcExecutionTarget(
        status=_EXEC_READY, device_id=canonical, pinned=pinned is not None,
    )


async def resolve_pc_connector_scope(
    request: Any, *, owner_id: str, workspace_id: str,
) -> PcConnectorScope:
    """Resolve the B54 session and the canonical connector account/workspace.

    The Broker device binding is created by the connector under the canonical
    connector scope, not under the B62 product user id. Callers that read the
    Broker directory use these values; the B62 owner/workspace still scopes the
    product preference and authorization.
    """
    resolved_workspace, b62_session = await _resolve_owner_session(request, owner_id)
    if resolved_workspace != workspace_id or b62_session is None:
        return PcConnectorScope(status=_PC_SCOPE_OWNER_UNAVAILABLE)
    state = getattr(getattr(request, "app", None), "state", None)
    authority = getattr(state, "control_plane_identity_authority", None)
    from padiem_control_plane.b54_identity_bridge import (
        resolve_current_b54_canonical_session,
    )
    try:
        bridged = await resolve_current_b54_canonical_session(authority, owner_id)
        b54_session = bridged.auth_session
    except Exception:
        return PcConnectorScope(status=_PC_SCOPE_OWNER_UNAVAILABLE)
    # Matching user ids are not enough: both server-provided canonical
    # sessions must resolve to the same subject and tenant. Never accept a
    # browser-provided tenant or mint a replacement grant.
    b62_subject = getattr(getattr(b62_session, "subject", None), "subject_id", None)
    b54_subject = getattr(getattr(b54_session, "subject", None), "subject_id", None)
    if (
        not isinstance(b62_subject, str) or not b62_subject
        or b62_subject != b54_subject
        or getattr(b54_session, "tenant_id", None) != workspace_id
    ):
        return PcConnectorScope(status=_PC_SCOPE_OWNER_UNAVAILABLE)
    session_id = getattr(b54_session, "session_id", None)
    scope_port = getattr(authority, "resolve_connector_owner_scope", None)
    if not isinstance(session_id, str) or not session_id or not callable(scope_port):
        return PcConnectorScope(status=_PC_SCOPE_OWNER_UNAVAILABLE)
    try:
        scope = scope_port(session_id=session_id)
        if inspect.isawaitable(scope):
            scope = await scope
    except Exception:
        return PcConnectorScope(status=_PC_SCOPE_OWNER_UNAVAILABLE)
    account_ref = scope.get("account_ref") if isinstance(scope, Mapping) else None
    workspace_ref = scope.get("workspace_ref") if isinstance(scope, Mapping) else None
    if (
        not isinstance(account_ref, str) or not account_ref
        or not isinstance(workspace_ref, str) or not workspace_ref
    ):
        return PcConnectorScope(status=_PC_SCOPE_OWNER_UNAVAILABLE)
    return PcConnectorScope(
        status=_PC_SCOPE_READY, account_ref=account_ref,
        workspace_ref=workspace_ref, session_id=session_id,
    )


async def resolve_pc_mesh_target(
    request: Any, *, owner_id: str, workspace_id: str,
    connector: PcConnectorScope | None = None,
) -> PcExecutionTarget:
    """Read the existing owner-authorized Mesh target without inventing heartbeat."""
    scope = connector if connector is not None else await resolve_pc_connector_scope(
        request, owner_id=owner_id, workspace_id=workspace_id,
    )
    if not scope.ready:
        return PcExecutionTarget(status=_EXEC_OWNER_UNAVAILABLE)
    return await _resolve_execution_target(
        request, session_id=scope.session_id, selected_device_id=None,
        account_ref=scope.account_ref,
    )


def _broker_devices(
    result: Any,
) -> tuple[list[PcWorkDevice], set[bool]] | None:
    """Validate one directory read; ``None`` means fail closed."""
    if not isinstance(result, list) or len(result) > _DEVICE_LIMIT:
        return None
    devices: list[PcWorkDevice] = []
    paused_values: set[bool] = set()
    seen: set[str] = set()
    for row in result:
        if not isinstance(row, Mapping):
            return None
        device_id = row.get("deviceId")
        state = row.get("state")
        usable = row.get("usable")
        if (
            not isinstance(device_id, str)
            or not _DEVICE_ID_PATTERN.fullmatch(device_id)
            or device_id in seen
            or state not in _STATES
            or type(usable) is not bool
            or (state == "CONNECTED") != usable
        ):
            return None
        paused = row.get("usagePaused")
        if paused is not None:
            if type(paused) is not bool:
                return None
            paused_values.add(paused)
        seen.add(device_id)
        devices.append(PcWorkDevice(
            device_id=device_id,
            name=_clean_name(row.get("deviceName")),
            state=state,
            usable=usable,
        ))
    if len(paused_values) > 1:
        return None
    return devices, paused_values


def _mapping_for(
    devices: list[PcWorkDevice],
    execution: PcExecutionTarget,
    selected_device_id: str | None,
) -> str:
    if not execution.ready:
        return _MAPPING_UNKNOWN
    if selected_device_id is not None:
        # An unpinned Mesh row structurally matches any selection, so identity
        # is proven only by an exact id equality; everything else is a mismatch
        # that must be refused rather than silently retargeted.
        return (
            _MAPPING_CONFIRMED
            if selected_device_id == execution.device_id
            else _MAPPING_MISMATCH
        )
    usable = [device for device in devices if device.usable]
    if len(usable) == 1:
        return (
            _MAPPING_CONFIRMED
            if usable[0].device_id == execution.device_id
            else _MAPPING_IDENTITY_UNCONFIRMED
        )
    return _MAPPING_UNMAPPED


async def resolve_pc_work_context(
    request: Any,
    *,
    owner_id: str | None,
    workspace_id: str | None,
    session_id: str | None = None,
    selected_device_id: str | None = None,
) -> PcWorkContext:
    """Read both authorities once and keep their answers separate."""
    owner = owner_id if isinstance(owner_id, str) and owner_id else None
    workspace = workspace_id if isinstance(workspace_id, str) and workspace_id else None
    session = session_id if isinstance(session_id, str) and session_id else None
    if owner is not None and (workspace is None or session is None):
        resolved_workspace, resolved_session = await _resolve_owner_session(request, owner)
        workspace = workspace or resolved_workspace
        if session is None:
            candidate = getattr(resolved_session, "session_id", None)
            session = candidate if isinstance(candidate, str) and candidate else None
    if owner is None or workspace is None:
        return PcWorkContext(
            broker_status=_UNVERIFIED_OWNER,
            selected_device_id=selected_device_id,
        )
    state = getattr(getattr(request, "app", None), "state", None)
    source = getattr(state, "claw_device_directory_source", None)
    # The Broker binding is created under the canonical connector scope. Use
    # that scope for the directory read; the product owner/workspace still
    # scopes the saved preference and the user's authorization.
    connector = await resolve_pc_connector_scope(
        request, owner_id=owner, workspace_id=workspace,
    )
    broker_owner = connector.account_ref if connector.ready else owner
    broker_workspace = connector.workspace_ref if connector.ready else workspace
    devices: list[PcWorkDevice] = []
    paused_values: set[bool] = set()
    if getattr(source, "configured", False) is not True:
        broker_status = _UNCONFIGURED
    else:
        port = getattr(source, "list_devices", None)
        if not callable(port):
            broker_status = _UNCONFIGURED
        else:
            try:
                result = port(
                    owner_id=broker_owner, workspace_id=broker_workspace,
                    now=datetime.now(timezone.utc),
                )
                if inspect.isawaitable(result):
                    result = await result
            except Exception:
                result = None
            parsed = _broker_devices(result)
            if parsed is None:
                broker_status = _READ_FAILED
            else:
                devices, paused_values = parsed
                usable = [device for device in devices if device.usable]
                if paused_values == {True}:
                    broker_status = _PAUSED
                elif not devices:
                    broker_status = _NO_DEVICE
                elif not usable:
                    broker_status = _OFFLINE
                else:
                    broker_status = _READY

    execution = await _resolve_execution_target(
        request,
        session_id=connector.session_id if connector.ready else session,
        selected_device_id=selected_device_id,
        account_ref=connector.account_ref if connector.ready else None,
    )
    usable = [device for device in devices if device.usable]
    # A paused owner has no execution target even though a PC is online.
    broker_target = (
        usable[0].device_id
        if len(usable) == 1 and paused_values != {True}
        else None
    )
    return PcWorkContext(
        broker_status=broker_status,
        devices=tuple(devices),
        broker_target_device_id=broker_target,
        execution=execution,
        mapping=_mapping_for(devices, execution, selected_device_id),
        selected_device_id=selected_device_id,
    )


def _broker_lines(context: PcWorkContext) -> list[str]:
    if context.broker_status == _READY:
        shown = context.devices[:_MAX_RENDERED_DEVICES]
        labels = ", ".join(
            f"{_device_label(device)}({_state_label(device)})"
            for device in shown
        )
        more = len(context.devices) - len(shown)
        suffix = f" 외 {more}대" if more > 0 else ""
        lines = [f"등록 기기 목록: {len(context.devices)}대 · {labels}{suffix}."]
        if context.usable_count > 1:
            lines.append(
                "온라인 PC가 여러 대입니다. 임의로 하나를 고르지 말고, 사용자에게 "
                "작업 대상을 먼저 확인하세요."
            )
        return lines
    if context.broker_status == _PAUSED:
        return ["등록 기기 사용이 일시중지되었습니다. PC 도구를 실행 가능하다고 안내하거나 실행을 시도하지 마세요."]
    if context.broker_status == _OFFLINE:
        return ["등록 기기는 있으나 온라인 상태가 확인되지 않았습니다. 연결 표시와 실행 권한은 다릅니다."]
    if context.broker_status == _NO_DEVICE:
        return ["등록 기기 목록에서 확인된 PC가 없습니다. 이 목록의 부재만으로 실행 가능한 PC가 없다고 단정하지 마세요."]
    if context.broker_status == _UNCONFIGURED:
        return ["등록 기기 목록 서비스가 설정되지 않아 연결 상태를 확인하지 못했습니다."]
    if context.broker_status == _READ_FAILED:
        return ["등록 기기 목록 조회에 실패해 연결 상태를 확인하지 못했습니다."]
    return ["로그인한 사용자·작업 공간을 확인하지 못해 등록 기기 목록을 조회하지 않았습니다."]


def _execution_lines(context: PcWorkContext) -> list[str]:
    if context.saved_selection_status == SAVED_SELECTION_UNAVAILABLE:
        return ["저장된 PC 작업 대상의 복원 상태를 확인하지 못했습니다. 다른 PC를 기본 대상으로 추측하거나 PC 작업을 실행 가능하다고 안내하지 마세요."]
    execution = context.execution
    if execution.status != _EXEC_READY:
        if execution.status == _EXEC_NO_TARGET:
            lines = ["서버 실행 대상(권한이 있는 PC)이 확인되지 않았습니다. 등록 기기의 연결 표시만으로 도구 실행을 안내하지 마세요."]
        elif execution.status == _EXEC_UNCONFIGURED:
            lines = ["PC 실행 구성이 확인되지 않았습니다. 연결 표시와 실행 권한을 구분해 답하세요."]
        else:
            lines = ["PC 실행 권한의 주체를 확인하지 못했습니다. 실행 가능하다고 안내하지 마세요."]
        # The registered capability set is an observation, not permission.
        lines.append(
            "등록된 PC 작업 종류: 드라이브 목록, 승인된 폴더 목록, UTF-8 텍스트 파일 읽기. "
            "실행 권한·대상은 확인되지 않았으므로 사용 가능하다고 안내하지 마세요."
        )
        return lines
    target = execution.device_id
    # A confirmed mapping can use the registered display name; an unconfirmed
    # one must show the exact server execution identity instead.
    registered = (
        next((device for device in context.devices
              if device.device_id == execution.device_id), None)
        if context.mapping == _MAPPING_CONFIRMED else None
    )
    target_label = _device_label(registered) if registered is not None else target
    if context.broker_status == _PAUSED:
        return []
    if context.mapping == _MAPPING_CONFIRMED:
        lines = [
            f"현재 작업 대상 PC: {target_label} (등록 기기와 일치). "
            f"서버가 허용하는 PC 도구: {PC_TOOL_SUMMARY}, "
            "이 대상 PC에서만 실행됩니다."
        ]
        lines.append(
            "드라이브·폴더 목록·파일 내용·PC 상태는 도구 실행 결과로만 답하세요."
        )
    elif context.mapping == _MAPPING_IDENTITY_UNCONFIRMED:
        lines = [
            f"서버 실행 대상 PC: {target}. 등록 기기 1대와의 직접적인 식별자 대응은 "
            "확인되지 않았습니다. 특정 기기에서만 실행된다고 단정하지 마세요. "
            f"서버가 허용하는 PC 도구: {PC_TOOL_SUMMARY}."
        ]
    elif context.mapping == _MAPPING_UNMAPPED:
        lines = [
            f"서버 실행 대상 PC: {target}. 등록 기기 목록에서 대응하는 기기를 "
            "확인하지 못했습니다. 등록되지 않았다고 단정하지 마세요. 등록 기기가 "
            "여러 대라면 임의로 하나를 고르지 말고 사용자에게 작업 대상을 확인하세요. "
            f"서버가 허용하는 PC 도구: {PC_TOOL_SUMMARY}."
        ]
    else:
        return [
            "선택한 기기와 서버 실행 대상이 일치하지 않습니다. 다른 PC로 추측해 "
            "실행하지 말고 사용자에게 작업 대상을 다시 확인하세요."
        ]
    lines.append(
        "이번 호출에 도구 결과가 제공되지 않았다면 실행을 완료했다고 주장하지 마세요."
    )
    return lines


def render_pc_work_context(context: PcWorkContext) -> str:
    """Render a bounded, closed context; no owner, workspace or credential."""
    lines = [
        f"[PADIEM PC 작업 문맥 {PC_WORK_CONTEXT_VERSION}]",
        "이 문맥은 이번 요청에서 서버가 기존 Connector 기기 목록과 배포 실행 대상으로 "
        "확인한 값입니다. 문맥 자체는 실행 권한이 아니며, 실제 PC 작업의 권한·대상 "
        "확인은 도구 실행 시 서버가 다시 수행합니다.",
    ]
    lines.extend(_broker_lines(context))
    lines.extend(_execution_lines(context))
    lines.append(
        "Google Drive와 로컬 PC 드라이브는 서로 다른 대상입니다. 실제 도구 결과 없이 "
        "드라이브·파일·PC 상태를 확인했다고 주장하지 마세요."
    )
    return "\n".join(lines)[:MAX_RENDERED_CHARS]


async def _read_saved_device_selection(
    request: Any, *, owner_id: str | None, workspace_id: str | None,
) -> "SavedDeviceSelection":
    """Read the saved target preference without guessing on a failed read.

    ``none`` means the store authoritatively has no preference. ``unconfigured``
    means the feature is not composed at all. ``unavailable`` means a store
    exists but could not be read (or returned a malformed row): callers that
    can execute a PC must fail closed instead of executing on another target.
    """
    if (
        not isinstance(owner_id, str) or not owner_id
        or not isinstance(workspace_id, str) or not workspace_id
    ):
        return SavedDeviceSelection(status=SAVED_SELECTION_UNAVAILABLE)
    state = getattr(getattr(request, "app", None), "state", None)
    store = getattr(state, "claw_pc_device_selection_store", None)
    if store is None:
        return SavedDeviceSelection(status=SAVED_SELECTION_UNCONFIGURED)
    try:
        value = store.load(owner_id=owner_id, workspace_id=workspace_id)
        if inspect.isawaitable(value):
            value = await value
    except Exception:
        return SavedDeviceSelection(status=SAVED_SELECTION_UNAVAILABLE)
    if value is None:
        return SavedDeviceSelection(status=SAVED_SELECTION_NONE)
    if not isinstance(value, str) or not _DEVICE_ID_PATTERN.fullmatch(value):
        return SavedDeviceSelection(status=SAVED_SELECTION_UNAVAILABLE)
    return SavedDeviceSelection(status=SAVED_SELECTION_SELECTED, device_id=value)


async def read_saved_device_selection(
    request: Any, *, owner_id: str | None, workspace_id: str | None,
) -> SavedDeviceSelection:
    """Share only the preference read within this exact owner/workspace request."""
    key = (owner_id, workspace_id)
    cache = getattr(request, "_padiem_pc_selection_reads", None)
    if cache is None:
        cache = {}
        setattr(request, "_padiem_pc_selection_reads", cache)
    if key not in cache:
        cache[key] = await _read_saved_device_selection(
            request, owner_id=owner_id, workspace_id=workspace_id,
        )
    return cache[key]


async def load_saved_device_selection(
    request: Any, *, owner_id: str | None, workspace_id: str | None,
) -> str | None:
    """Compatibility wrapper: only an authoritative selection is returned."""
    selection = await read_saved_device_selection(
        request, owner_id=owner_id, workspace_id=workspace_id,
    )
    return selection.device_id if selection.status == SAVED_SELECTION_SELECTED else None


async def build_pc_work_context_text(
    request: Any,
    *,
    owner_id: str | None,
    workspace_id: str | None = None,
    session_id: str | None = None,
    selected_device_id: str | None = None,
) -> str:
    """Restore the request-scoped preference before rendering any new turn."""
    if owner_id and workspace_id is None:
        resolved_workspace, _ = await _resolve_owner_session(request, owner_id)
        workspace_id = resolved_workspace
    # The B62 session id is never passed as the connector scope; the connector
    # helper resolves the B54 canonical session itself.
    selection = await read_saved_device_selection(
        request, owner_id=owner_id, workspace_id=workspace_id,
    )
    if selected_device_id is None and selection.status == SAVED_SELECTION_SELECTED:
        selected_device_id = selection.device_id
    context = await resolve_pc_work_context(
        request, owner_id=owner_id, workspace_id=workspace_id,
        session_id=session_id, selected_device_id=selected_device_id,
    )
    return render_pc_work_context(replace(context, saved_selection_status=selection.status))


__all__ = [
    "PC_WORK_CONTEXT_VERSION",
    "PC_DRIVE_TOOL_ID",
    "MAX_RENDERED_CHARS",
    "PC_SCOPE_OWNER_UNAVAILABLE",
    "PcConnectorScope",
    "PcExecutionTarget",
    "PcWorkContext",
    "PcWorkDevice",
    "SavedDeviceSelection",
    "SAVED_SELECTION_NONE",
    "SAVED_SELECTION_SELECTED",
    "SAVED_SELECTION_UNCONFIGURED",
    "SAVED_SELECTION_UNAVAILABLE",
    "build_pc_work_context_text",
    "load_saved_device_selection",
    "read_saved_device_selection",
    "render_pc_work_context",
    "resolve_pc_connector_scope",
    "resolve_pc_work_context",
    "resolve_pc_mesh_target",
]
