"""#8037 공유 명령 제한 시험의 공용 대역 — 엔진 서명 호출 하니스.

기존 시험 하니스(test_261109_pc_dispatch_workspace_seam)를 그대로 재사용한다.
공용 헬퍼는 _support 아래 두어 시험끼리의 import 수치를 늘리지 않는다(#8061).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import oracle_mesh_read_return_routes as routes  # noqa: E402
import test_261109_pc_dispatch_workspace_seam as seam  # noqa: E402

OWNER = seam.OWNER
SUBJECT = seam.SUBJECT
ACCOUNT = seam.ACCOUNT
WORKSPACE = seam.WORKSPACE
RUN = seam.RUN
DEVICE = seam.DEVICE
NODE = seam.NODE
CHANNEL_SECRET = seam.CHANNEL_SECRET
LIST_CALL = seam.LIST_CALL


def engine_state(monkeypatch, roots):
    """승인 루트 집합을 목표 해석으로 고정하고 실제 스테이징 저장소를 쓴다."""
    session = seam._session(tenant_id=WORKSPACE)
    history = seam._History(run_workspace=WORKSPACE)
    state = seam._state(monkeypatch, session, history, WORKSPACE)

    async def resolved_target(request, *, session, selected_device_id, user_id):
        return {
            "authorized": True,
            "target": {"node_ref": NODE, "device_id": DEVICE},
            "roots": roots,
            "account_ref": ACCOUNT,
            "workspace_ref": WORKSPACE,
        }, None

    monkeypatch.setattr(routes, "_engine_pc_files_target", resolved_target)
    return state, history


def engine_dispatch(state, payload):
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(
        seam._SignedRequest(state, payload),
    ))
    return response.status_code, json.loads(response.body)


class PollStore:
    """폴드 한 번에 claimable 행 하나를 돌려주는 저장소 대역."""

    def __init__(self, row):
        self.row = row
        self.claimed = []

    async def oldest_pending_oracle_mesh_dispatch(self):
        return dict(self.row) if self.row is not None else None

    async def claim_oracle_mesh_dispatch(self, *, dispatch_id, nonce_sha256):
        self.claimed.append(dispatch_id)
        return True


def poll_request(store):
    source = routes.build_oracle_mesh_return_source(
        seam._mapping(), CHANNEL_SECRET, routes.EXECUTION_MODE_MESH,
    )
    state = SimpleNamespace(
        oracle_mesh_return_source=source, history_store=store,
        settings=SimpleNamespace(mcp_pc_session_enabled=False, public_base_url=""),
        desktop_text_store=None,
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=state),
        headers={routes.ORACLE_MESH_CHANNEL_HEADER: CHANNEL_SECRET},
    )


def poll_row(**overrides):
    from datetime import datetime, timedelta, timezone

    row = {
        "dispatch_id": "dsp_" + "a" * 32, "user_id": OWNER, "run_id": RUN,
        "kind": "command", "command_text": "$padiemShareTargets=@()\nGet-ChildItem x",
        "command_id": "cmd-1", "tool_request_ref": "ref-1", "request_id": "req-1",
        "revision_ref": "rev-1", "evidence_ref": None, "request_fingerprint": "f" * 64,
        "account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
        "device_id": DEVICE, "binding_ref": None, "node_ref": NODE,
        "root_ref": routes._COMMAND_ROOT_REF,
        "path_relative": routes._COMMAND_PATH_RELATIVE,
        "file_path": routes._COMMAND_FILE_SENTINEL,
        "nonce_sha256": None, "state": "pending", "user_mode": 0,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5))
        .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    row.update(overrides)
    return row


def mcp_call(monkeypatch, tool, arguments, *, roots=None):
    """외부 커넥터(MCP) 경로 한 번 — 기존 등록 폴더 하니스를 그대로 쓴다."""
    from test_261105_mcp_registered_folders import _call

    return _call(monkeypatch, tool, arguments, roots=roots)