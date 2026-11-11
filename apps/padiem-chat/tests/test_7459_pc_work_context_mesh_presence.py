"""#7459 6-(3): Broker 미설정 호스트(컴2)에서도 페어링 PC·Mesh 프레즌스로 연결 상태 문맥을 만든다.

입력창 위 연결 배지(/api/claw/local-access/devices)는 Broker 소스가 미설정이어도
계정 페어링 PC(links_for_owner)와 검증된 Mesh 대상에 대해 mesh_device_presence_store를
조회해 온라인으로 표시하지만, 기존 pc_work_context는 broker_status="unconfigured"를
유지해 모델 문맥에 "등록 기기 목록 서비스가 설정되지 않아 연결 상태를 확인하지 못했습니다."를
넣었고, 모델 생각(thinking)에 "connection status service not set"이 노출됐다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.model_first import model_first_context
from app.pc_work_context import render_pc_work_context, resolve_pc_work_context

OWNER = "usr_" + "9" * 32
WORKSPACE = "tenant-7459"
SESSION = "sess-7459"
CONNECTOR_ACCOUNT = "acct-7459"
UNCONFIGURED_COPY = "등록 기기 목록 서비스가 설정되지 않아 연결 상태를 확인하지 못했습니다."


class _Identity:
    async def resolve_connector_owner_scope(self, *, session_id: str):
        assert session_id in (SESSION, "sess-b54")
        return {"account_ref": CONNECTOR_ACCOUNT, "workspace_ref": "ws-connector"}


class _Mesh:
    configured = True
    execution_mode = "mesh"

    def __init__(self, device_id: str | None = "node-com1", node_ref: str = "node-com1"):
        self._device_id = device_id
        self._node_ref = node_ref

    def command_target(self, *, account_ref: str, device_id: str | None = None):
        if account_ref != CONNECTOR_ACCOUNT:
            return None
        if device_id is not None and device_id not in (self._device_id, self._node_ref):
            return None
        return {
            "account_ref": CONNECTOR_ACCOUNT,
            "device_id": self._device_id,
            "node_ref": self._node_ref,
            "command_exec": True,
        }


class _PairingStore:
    def __init__(self, rows):
        self._rows = list(rows)

    async def links_for_owner(self, *, user_id: str):
        assert user_id == OWNER
        return list(self._rows)


class _PresenceStore:
    def __init__(self, online_ids: set[str]):
        self._online = set(online_ids)

    async def load(self, *, device_id: str):
        return {
            "device_id": device_id,
            "connected": device_id in self._online,
            "received_at": (datetime.now(timezone.utc) - timedelta(seconds=5))
            .isoformat()
            .replace("+00:00", "Z"),
            "credential_generation": None,
            "source": "mesh",
        }


def _com2_request(*, links=None, online_ids=None, mesh=None, directory_source=None):
    state = SimpleNamespace(
        claw_device_directory_source=directory_source,
        oracle_mesh_return_source=mesh,
        control_plane_identity_authority=_Identity(),
        identity_shadow_store=None,
        pc_device_pairing_store=_PairingStore(links) if links is not None else None,
        mesh_device_presence_store=_PresenceStore(online_ids) if online_ids is not None else None,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_7459_unconfigured_broker_with_online_linked_pc_reports_ready_not_unconfigured():
    request = _com2_request(
        links=[{"mesh_node_id": "node-com1", "label": "대표 PC", "state": "active"}],
        online_ids={"node-com1"},
        mesh=_Mesh("node-com1"),
    )
    context = asyncio.run(
        resolve_pc_work_context(
            request,
            owner_id=OWNER,
            workspace_id=WORKSPACE,
            session_id=SESSION,
        )
    )
    assert context.broker_status == "ready"
    assert context.usable_count == 1
    assert context.mapping == "confirmed"
    assert context.tool_available is True

    rendered = render_pc_work_context(context)
    assert UNCONFIGURED_COPY not in rendered
    assert "등록 기기 목록: 1대 · 대표 PC(온라인)." in rendered
    assert "현재 작업 대상 PC: 대표 PC (등록 기기와 일치)" in rendered

    from unittest.mock import patch

    b62 = SimpleNamespace(
        session_id="sess-b62",
        tenant_id=WORKSPACE,
        subject=SimpleNamespace(subject_id="sub-7459"),
    )
    b54 = SimpleNamespace(
        session_id="sess-b54",
        tenant_id=WORKSPACE,
        subject=SimpleNamespace(subject_id="sub-7459"),
    )

    async def _owner_session(_req, _uid):
        return WORKSPACE, b62

    async def _b54_session(_authority, _uid):
        return SimpleNamespace(auth_session=b54)

    with (
        patch("app.pc_work_context._resolve_owner_session", side_effect=_owner_session),
        patch(
            "padiem_control_plane.b54_identity_bridge.resolve_current_b54_canonical_session",
            side_effect=_b54_session,
        ),
    ):
        mf_context = asyncio.run(
            model_first_context(request, owner_id=OWNER, grounding_context=None)
        )
    assert mf_context is not None
    assert UNCONFIGURED_COPY not in mf_context
    assert "대표 PC(온라인)" in mf_context


def test_7459_unconfigured_broker_with_offline_linked_pc_reports_offline_not_unconfigured():
    request = _com2_request(
        links=[{"mesh_node_id": "node-com1", "label": "대표 PC", "state": "active"}],
        online_ids=set(),
        mesh=_Mesh("node-com1"),
    )
    context = asyncio.run(
        resolve_pc_work_context(
            request,
            owner_id=OWNER,
            workspace_id=WORKSPACE,
            session_id=SESSION,
        )
    )
    assert context.broker_status == "offline"
    assert context.usable_count == 0
    rendered = render_pc_work_context(context)
    assert UNCONFIGURED_COPY not in rendered
    assert "온라인 상태가 확인되지 않았습니다" in rendered


def test_7459_unconfigured_broker_with_verified_mesh_target_and_presence_reports_ready():
    request = _com2_request(
        links=[],
        online_ids={"node-com1"},
        mesh=_Mesh("node-com1"),
    )
    context = asyncio.run(
        resolve_pc_work_context(
            request,
            owner_id=OWNER,
            workspace_id=WORKSPACE,
            session_id=SESSION,
        )
    )
    assert context.broker_status == "ready"
    assert context.usable_count == 1
    assert context.mapping == "confirmed"
    rendered = render_pc_work_context(context)
    assert UNCONFIGURED_COPY not in rendered
    assert "node-com1(온라인)" in rendered


def test_7459_truly_unconfigured_host_without_links_or_mesh_keeps_unconfigured():
    request = _com2_request(links=None, online_ids=None, mesh=None)
    context = asyncio.run(
        resolve_pc_work_context(
            request,
            owner_id=OWNER,
            workspace_id=WORKSPACE,
            session_id=SESSION,
        )
    )
    assert context.broker_status == "unconfigured"
    assert UNCONFIGURED_COPY in render_pc_work_context(context)
