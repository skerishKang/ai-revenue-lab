"""MCP 도구가 대상 PC를 고르는 한 자리(대표 요청 2026-11-04).

pc_devices가 돌려주는 표시 정보(라벨·기기 ID 끝 6자)와 도구 호출의 ``device``
인자를 소유자의 연결 PC 목록(``pc_device_links``, 단일 원천)으로 풀어 쓴다.
전체 기기 ID나 메시 노드 ID는 이 계층을 벗어나 클라이언트에 내려가지 않는다 —
목록은 끝 6자만 주고, 호출이 고른 PC는 서버가 소유자 목록으로 되풀이한다.

범위(device scope)는 동의 화면의 결정이 토큰에 새겨진 것(마이그레이션 100)을
읽는다. NULL은 이전에 발급된 단일 PC 토큰 — 토큰에 묶인 PC만 허용한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from padiem_ai_core.pc_device_identity import is_pc_device_id

_ID6_CHARS = 6
_MAX_LINKS = 20


class McpDeviceRefusal(Exception):
    """거절 이유 코드와 한국어 안내를 한 묶음으로 들고 있는 선택 실패."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def device_id6(device_id: Any) -> str:
    """클라이언트에 내려가는 유일한 기기 식별자: 끝 6자뿐이다.

    노드 형식(``node/<도메인>/<이름>``)과 구식(``id@도메인``) 모두 마지막
    조각의 끝에서부터 읽고, 식별자 문자셋 밖의 글자는 떼어 낸다. 소유자의 몇
    안 되는 기기 사이에서 겹치면 호출이 모호하다고 답하므로, 이 값은 식별에
    쓰이지 권한의 근거가 되지 않는다.
    """
    if not isinstance(device_id, str) or not device_id:
        return ""
    tail = device_id.rsplit("/", 1)[-1].rsplit("@", 1)[-1]
    cleaned = "".join(ch for ch in tail if ch.isalnum() or ch in "-_.")
    return cleaned[-_ID6_CHARS:] if cleaned else ""


def _link_targets(links: Any) -> list[dict[str, Any]]:
    """활성 링크 행을 (기기 ID, 라벨) 목록으로 접는다. 순서는 원본 유지."""
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in links if isinstance(links, list) else []:
        if not isinstance(link, dict):
            continue
        device_id = link.get("mesh_node_id")
        if not is_pc_device_id(device_id) or device_id in seen:
            continue
        seen.add(device_id)
        label = link.get("label")
        targets.append({
            "device_id": device_id,
            "label": label.strip() if isinstance(label, str) and label.strip() else None,
            "id6": device_id6(device_id),
        })
        if len(targets) >= _MAX_LINKS:
            break
    return targets


def _allowed_device_ids(principal: Any, targets: list[dict[str, Any]]) -> set[str] | None:
    """토큰 범위가 허용하는 기기 ID 집합. None은 판정 불가(거급)."""
    scope = principal.get("device_scope") if isinstance(principal, dict) else None
    if scope == "all":
        return {item["device_id"] for item in targets}
    if scope == "selected":
        raw = principal.get("device_scope_json") if isinstance(principal, dict) else None
        try:
            chosen = json.loads(raw) if isinstance(raw, str) else None
        except ValueError:
            return None
        if not isinstance(chosen, list):
            return None
        return {item for item in chosen if is_pc_device_id(item)}
    # NULL(레거시 단일 PC 토큰)과 그 외 값: 토큰에 묶인 PC 하나만 허용한다.
    bound = principal.get("device_id") if isinstance(principal, dict) else None
    return {bound} if is_pc_device_id(bound) else None


async def _owner_targets(request: Any, owner_id: str) -> list[dict[str, Any]]:
    pairing = getattr(request.app.state, "pc_device_pairing_store", None)
    if not callable(getattr(pairing, "links_for_owner", None)):
        raise McpDeviceRefusal("device_directory_unavailable", "연결 PC 목록을 지금 읽을 수 없습니다.")
    try:
        links = await pairing.links_for_owner(user_id=owner_id)
    except Exception:
        raise McpDeviceRefusal("device_directory_unavailable", "연결 PC 목록을 지금 읽을 수 없습니다.")
    return _link_targets(links)


async def resolve_target_device(request: Any, *, owner_id: str, principal: Any,
                                device_arg: Any) -> dict[str, Any]:
    """``device`` 인자를 소유자의 연결 PC 하나로 풀어 쓴다.

    pc_devices가 준 끝 6자 식별자나 표시 이름으로 받는다. 소유자의 연결 PC가
    아니면 ``device_not_linked``, 토큰 범위 밖이면
    ``device_not_in_token_scope``, 두 기기가 같은 끝 6자(또는 같은 이름)를
    가지면 ``device_ambiguous``로 거절한다.
    """
    if not isinstance(device_arg, str) or not device_arg.strip():
        raise McpDeviceRefusal("device_not_linked", "대상 PC를 확인할 수 없습니다.")
    wanted = device_arg.strip()
    targets = await _owner_targets(request, owner_id)
    matches = [item for item in targets
               if item["id6"] == wanted
               or (item["label"] is not None and item["label"] == wanted)]
    if len(matches) != 1:
        code = "device_ambiguous" if len(matches) > 1 else "device_not_linked"
        raise McpDeviceRefusal(code, "요청한 PC를 이 계정의 연결 PC로 확인할 수 없습니다.")
    target = matches[0]
    allowed = _allowed_device_ids(principal, targets)
    if allowed is None or target["device_id"] not in allowed:
        raise McpDeviceRefusal("device_not_in_token_scope",
                               "이 연결(토큰)이 허용한 PC 범위 밖입니다.")
    return {"device_id": target["device_id"], "id6": target["id6"]}


async def list_owner_devices(request: Any, *, owner_id: str, principal: Any) -> list[dict[str, Any]]:
    """``pc_devices`` 답변: 표시 이름·끝 6자·온라인 여부·기본 PC 여부."""
    targets = await _owner_targets(request, owner_id)
    allowed = _allowed_device_ids(principal, targets) or set()
    presence = getattr(request.app.state, "mesh_device_presence_store", None)
    loader = getattr(presence, "load", None)
    token_device = principal.get("device_id") if isinstance(principal, dict) else None
    now = datetime.now(timezone.utc)
    devices: list[dict[str, Any]] = []
    for item in targets:
        online = False
        if callable(loader):
            try:
                row = loader(device_id=item["device_id"])
                if hasattr(row, "__await__"):
                    row = await row
            except Exception:
                row = None
            # 함수 수입: 워커 임포트 그래프에 이 경로의 PC 계층을 끌어들이지
            # 않기 위해, 실행 시점에만 온라인 판정기를 읽는다.
            from .claw_local_access_source import mesh_presence_online
            online = mesh_presence_online(row, device_id=item["device_id"], now=now)
        devices.append({
            "name": item["label"],
            "id6": item["id6"],
            "online": online,
            "default": item["device_id"] == token_device,
            "in_scope": item["device_id"] in allowed,
        })
    return devices
