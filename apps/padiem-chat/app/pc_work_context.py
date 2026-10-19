"""#5015: one server-verified PC work context for Chat and Claw model calls.

The context is a per-request observation of the *existing* canonical Broker
device directory (#4418) that the "내 컴퓨터" panel already reads. It is not a
second online authority, not a cached browser preference and not an execution
grant: every tool dispatch still re-verifies owner, workspace and device at
execution time.

A new conversation therefore sees the account's current PC state because the
context is resolved live from the signed-in owner's directory, not restored
from browser memory. No idle polling is added; one request makes at most one
directory read, and an unconfigured/unreadable directory renders a truthful
"unverified" context instead of guessing.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

PC_WORK_CONTEXT_VERSION = "padiem-pc-work-context.v1"
PC_DRIVE_TOOL_ID = "claw.pc.query_drives"
PC_DRIVE_TOOL_CAPABILITY = "읽기 전용 파일 시스템 드라이브 목록"
MAX_RENDERED_CHARS = 1400
MAX_DEVICE_NAME_CHARS = 60
_MAX_RENDERED_DEVICES = 8
_DEVICE_LIMIT = 24
_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_STATES = ("CONNECTED", "OFFLINE", "REVOKED")

_READY = "ready"
_NO_DEVICE = "no_device"
_OFFLINE = "offline"
_PAUSED = "paused"
_UNCONFIGURED = "unconfigured"
_READ_FAILED = "read_failed"
_UNVERIFIED_OWNER = "unverified_owner"


@dataclass(frozen=True, slots=True)
class PcWorkDevice:
    device_id: str
    name: str | None
    state: str
    usable: bool


@dataclass(frozen=True, slots=True)
class PcWorkContext:
    status: str
    devices: tuple[PcWorkDevice, ...] = ()
    target_device_id: str | None = None

    @property
    def verified(self) -> bool:
        return self.status in (_READY, _NO_DEVICE, _OFFLINE, _PAUSED)

    @property
    def usable_count(self) -> int:
        return sum(1 for device in self.devices if device.usable)


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


async def resolve_pc_work_context(
    request: Any, *, owner_id: str | None, workspace_id: str | None,
) -> PcWorkContext:
    """Read the owner/workspace-scoped directory once; never pick first-of-many.

    Selection is only a target hint. Exactly one usable device becomes the
    explicit default target; two or more usable devices stay ambiguous so the
    model asks the user instead of silently choosing one.
    """
    if not isinstance(owner_id, str) or not owner_id:
        return PcWorkContext(status=_UNVERIFIED_OWNER)
    if not isinstance(workspace_id, str) or not workspace_id:
        return PcWorkContext(status=_UNVERIFIED_OWNER)
    source = getattr(getattr(request, "app", None), "state", None)
    source = getattr(source, "claw_device_directory_source", None)
    if getattr(source, "configured", False) is not True:
        return PcWorkContext(status=_UNCONFIGURED)
    port = getattr(source, "list_devices", None)
    if not callable(port):
        return PcWorkContext(status=_UNCONFIGURED)
    try:
        result = port(
            owner_id=owner_id, workspace_id=workspace_id,
            now=datetime.now(timezone.utc),
        )
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        return PcWorkContext(status=_READ_FAILED)
    if not isinstance(result, list) or len(result) > _DEVICE_LIMIT:
        return PcWorkContext(status=_READ_FAILED)

    devices: list[PcWorkDevice] = []
    paused_values: set[bool] = set()
    seen: set[str] = set()
    for row in result:
        if not isinstance(row, Mapping):
            return PcWorkContext(status=_READ_FAILED)
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
            return PcWorkContext(status=_READ_FAILED)
        paused = row.get("usagePaused")
        if paused is not None:
            if type(paused) is not bool:
                return PcWorkContext(status=_READ_FAILED)
            paused_values.add(paused)
        seen.add(device_id)
        devices.append(PcWorkDevice(
            device_id=device_id,
            name=_clean_name(row.get("deviceName")),
            state=state,
            usable=usable,
        ))
    if len(paused_values) > 1:
        return PcWorkContext(status=_READ_FAILED)

    usable = [device for device in devices if device.usable]
    target = usable[0].device_id if len(usable) == 1 else None
    if paused_values == {True}:
        status = _PAUSED
    elif not devices:
        status = _NO_DEVICE
    elif not usable:
        status = _OFFLINE
    else:
        status = _READY
    return PcWorkContext(status=status, devices=tuple(devices), target_device_id=target)


def render_pc_work_context(context: PcWorkContext) -> str:
    """Render a bounded, closed context; no owner, workspace or credential."""
    lines = [
        f"[PADIEM PC 작업 문맥 {PC_WORK_CONTEXT_VERSION}]",
        "이 문맥은 이번 요청에서 서버가 기존 Connector 기기 목록으로 확인한 값입니다. "
        "문맥 자체는 실행 권한이 아니며, 실제 PC 작업의 권한·대상 확인은 도구 실행 시 "
        "서버가 다시 수행합니다.",
    ]
    if context.status == _READY:
        if context.target_device_id is not None:
            target = next(
                device for device in context.devices
                if device.device_id == context.target_device_id
            )
            lines.append(
                f"현재 작업 대상 PC: {_device_label(target)}. "
                "사용 가능한 PC 도구: 드라이브 목록, 승인된 폴더 목록, "
                "UTF-8 텍스트 파일 읽기. 실제 실행 대상·권한은 도구 실행 시 "
                "서버가 다시 확인합니다."
            )
            lines.append(
                "드라이브·폴더 목록·파일 내용·PC 상태는 도구 실행 결과로만 "
                "답하세요."
            )
        else:
            # Two or more usable PCs: never silently pick one.
            lines.append(
                "온라인 PC가 여러 대입니다. 임의로 하나를 고르지 말고, 사용자에게 "
                "작업 대상을 먼저 확인하세요."
            )
        # The device list is bounded; the target/tool lines above are not
        # pushed out by a large account directory.
        shown = context.devices[:_MAX_RENDERED_DEVICES]
        labels = ", ".join(
            f"{_device_label(device)}({_state_label(device)})"
            for device in shown
        )
        more = len(context.devices) - len(shown)
        suffix = f" 외 {more}대" if more > 0 else ""
        lines.append(f"확인된 PC: {len(context.devices)}대 · {labels}{suffix}.")
    elif context.status == _PAUSED:
        lines.append(
            "사용자가 PC 작업을 일시중지했습니다. PC 도구를 실행 가능하다고 안내하거나 "
            "실행을 시도하지 마세요."
        )
    elif context.status == _OFFLINE:
        lines.append(
            "등록된 PC는 있으나 현재 온라인 상태가 확인되지 않았습니다. PC 도구를 "
            "실행 가능하다고 안내하지 말고, 연결 상태 확인을 안내하세요."
        )
    elif context.status == _NO_DEVICE:
        lines.append(
            "이 계정에서 확인된 연결 PC가 없습니다. PC 작업을 완료했다고 주장하지 말고 "
            "연결 설치·승인을 안내하세요."
        )
    elif context.status in (_UNCONFIGURED, _READ_FAILED):
        lines.append(
            "서버에서 PC 연결 상태를 확인하지 못했습니다. 연결 여부를 추측하거나 "
            "'도구가 없다'고 단정하지 말고, 현재 확인할 수 없다고 답하세요."
        )
    else:
        lines.append(
            "로그인한 사용자·작업 공간을 확인하지 못해 PC 상태를 조회하지 않았습니다. "
            "PC 연결을 확인했다고 주장하지 마세요."
        )
    lines.append(
        "Google Drive와 로컬 PC 드라이브는 서로 다른 대상입니다. 실제 도구 결과 없이 "
        "드라이브·파일·PC 상태를 확인했다고 주장하지 마세요."
    )
    rendered = "\n".join(lines)
    return rendered[:MAX_RENDERED_CHARS]


async def build_pc_work_context_text(
    request: Any,
    *,
    owner_id: str | None,
    workspace_id: str | None = None,
) -> str:
    """Resolve the workspace when absent, then render the one model context."""
    owner = owner_id if isinstance(owner_id, str) and owner_id else None
    workspace = workspace_id if isinstance(workspace_id, str) and workspace_id else None
    if owner is not None and workspace is None:
        from .claw_memory_routes import _resolve_memory_workspace

        try:
            resolved = await _resolve_memory_workspace(request, owner)
        except Exception:
            resolved = None
        workspace = resolved if isinstance(resolved, str) and resolved else None
    context = await resolve_pc_work_context(
        request, owner_id=owner, workspace_id=workspace,
    )
    return render_pc_work_context(context)


__all__ = [
    "PC_WORK_CONTEXT_VERSION",
    "PC_DRIVE_TOOL_ID",
    "MAX_RENDERED_CHARS",
    "PcWorkContext",
    "PcWorkDevice",
    "build_pc_work_context_text",
    "render_pc_work_context",
    "resolve_pc_work_context",
]
