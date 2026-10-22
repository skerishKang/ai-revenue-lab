"""#5015: /api/orchestration honors the server-verified browser tier.

The real orchestration route, the real PC files lane and the real tier-aware
resolver run against a recording Engine transport. No provider, Mesh, D1 or
network call is made. The browser tier is checked through the same grade and
administrator gates the Chat stream route already applies.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from app import orchestration_routes as routes
from app.model_policy import ADMIN_B14_MODEL_ID
from app.orchestration_bridge import B62EngineOrchestrationBridge
from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    active_route_for,
)

OWNER = "usr_" + "a" * 32
SUBJECT = "sub_" + "a" * 32
WORKSPACE = "ws_" + "a" * 32
PC_TEXT = (
    "내 PC의 MeshCentralTrial 폴더에서 파일 목록을 보고, "
    "meshcentral-padiem-trial.txt 파일 내용을 읽어줘"
)
ALIASED_TEXT = "/plus " + PC_TEXT


class _RecordingBridge(B62EngineOrchestrationBridge):
    """The real bridge request builder with the Engine transport recorded."""

    def __init__(self) -> None:
        super().__init__(client=object(), store=object())
        self.requests: list[dict] = []

    async def start(self, **fields):
        self.requests.append(self.build_engine_request(
            user_id=fields["user_id"],
            messages=fields["messages"],
            skill=fields["skill"],
            model_id=fields["model_id"],
            conversation_id=fields["conversation_id"],
            additional_system_context=fields.get("additional_system_context"),
            subject_id=fields.get("subject_id"),
            agent_plan=fields.get("agent_plan"),
            tool_arguments=fields.get("tool_arguments"),
            session_id=fields.get("session_id"),
        ))
        return SimpleNamespace(answer="ok")


class _History:
    def __init__(self) -> None:
        self.runs: list[dict] = []
        self.sealed: list[dict] = []

    async def record_chat_pc_drive_run(self, **fields):
        self.runs.append(fields)
        return "chat_" + "s" * 32

    async def get_claw_run(self, user_id, run_id):
        return {
            "run_id": run_id,
            "conversation_id": "chat_" + "s" * 32,
            "result_summary": "ok",
            "action": "pc_files_query",
        }

    async def seal_run_terminal(self, **fields):
        self.sealed.append(fields)
        return True


class _AdminStore:
    def __init__(self, is_admin: bool) -> None:
        self.is_admin = is_admin

    async def is_google_admin(self, user_id):
        return self.is_admin

    async def runtime_access(self, user_id):
        return {"status": "approved", "tier": "max"}


def _install(monkeypatch, *, is_admin: bool):
    import app.chat_pc_drive as lane
    import app.pc_work_context as context

    bridge = _RecordingBridge()
    history = _History()

    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)

    monkeypatch.setattr(lane, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane, "current_user_id", lambda request: OWNER)

    async def owner(request, uid):
        return SimpleNamespace(session_id="sess"), SUBJECT, WORKSPACE

    async def grant(request, session, *, device_id=None):
        return True

    async def selection(request, *, owner_id, workspace_id):
        return SimpleNamespace(status="none", device_id=None)

    async def work_context(
        request, *, owner_id, workspace_id, session_id, selected_device_id,
    ):
        # The turn has a verified PC; this harness only exercises tier/model
        # selection, so the inventory is one READY device.
        return SimpleNamespace(
            devices=(SimpleNamespace(device_id="node/mesh/owner-pc", state="READY"),),
            selected_confirmed=False,
            execution=SimpleNamespace(ready=False),
        )

    monkeypatch.setattr(lane, "_resolve_chat_owner", owner)
    monkeypatch.setattr(lane, "_check_mesh_grant", grant)
    monkeypatch.setattr(context, "read_saved_device_selection", selection)
    monkeypatch.setattr(context, "resolve_pc_work_context", work_context)
    monkeypatch.setattr(context, "render_pc_work_context", lambda pc_context: "")
    return bridge, history, _AdminStore(is_admin)


def _request(payload, bridge, history, admin_store):
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/orchestration",
        "headers": [(b"content-type", b"application/json")],
    })
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=bridge,
            history_store=history,
            usage_gate_enforced=False,
            usage_gate=None,
            b66_member_admin_store=admin_store,
            settings=SimpleNamespace(runtime_mode="mock"),
        )
    )
    request._body = json.dumps(payload).encode("utf-8")
    return request


def _payload(tier: str, text: str = PC_TEXT) -> dict:
    return {"messages": [{"role": "user", "content": text}], "tier": tier}


def test_admin_tier_reaches_the_pc_files_engine_request(monkeypatch) -> None:
    bridge, history, admin_store = _install(monkeypatch, is_admin=True)

    response = asyncio.run(routes.api_orchestration(
        _request(_payload("admin"), bridge, history, admin_store),
    ))

    assert response.status_code == 200
    assert len(bridge.requests) == 1
    assert bridge.requests[0]["agent"]["model_policy"] == {
        "model": ADMIN_B14_MODEL_ID,
    }
    assert bridge.requests[0]["agent_plan"]["agent_id"] == "agent:padiem:chat-pc-query@1"
    assert history.runs[0]["action"] == "pc_files_query"


def test_non_admin_admin_tier_is_refused_before_the_lane(monkeypatch) -> None:
    bridge, history, admin_store = _install(monkeypatch, is_admin=False)

    response = asyncio.run(routes.api_orchestration(
        _request(_payload("admin"), bridge, history, admin_store),
    ))

    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "admin_forbidden"
    assert bridge.requests == []
    assert history.runs == []


def test_plus_tier_reaches_the_pc_files_engine_request(monkeypatch) -> None:
    bridge, history, admin_store = _install(monkeypatch, is_admin=False)
    expected = active_route_for(ProductTierLabel.PLUS).model_id

    response = asyncio.run(routes.api_orchestration(
        _request(_payload("plus"), bridge, history, admin_store),
    ))

    assert response.status_code == 200
    assert len(bridge.requests) == 1
    assert bridge.requests[0]["agent"]["model_policy"] == {"model": expected}
    assert bridge.requests[0]["agent"]["model_policy"]["model"] != (
        active_route_for(ProductTierLabel.FREE).model_id
    )


def test_legacy_alias_without_tier_keeps_its_model_and_cleans_the_prompt(
    monkeypatch,
) -> None:
    bridge, history, admin_store = _install(monkeypatch, is_admin=False)
    expected = active_route_for(ProductTierLabel.PLUS).model_id

    response = asyncio.run(routes.api_orchestration(
        _request(
            {"messages": [{"role": "user", "content": ALIASED_TEXT}]},
            bridge, history, admin_store,
        ),
    ))

    assert response.status_code == 200
    assert bridge.requests[0]["agent"]["model_policy"] == {"model": expected}
    assert bridge.requests[0]["messages"][0]["content"] == PC_TEXT
    assert history.runs[0]["user_text"] == ALIASED_TEXT


def test_admin_tier_replaces_the_alias_in_the_engine_prompt(monkeypatch) -> None:
    bridge, history, admin_store = _install(monkeypatch, is_admin=True)

    response = asyncio.run(routes.api_orchestration(
        _request(_payload("admin", ALIASED_TEXT), bridge, history, admin_store),
    ))

    assert response.status_code == 200
    assert bridge.requests[0]["agent"]["model_policy"] == {
        "model": ADMIN_B14_MODEL_ID,
    }
    assert bridge.requests[0]["messages"][0]["content"] == PC_TEXT
    assert history.runs[0]["user_text"] == ALIASED_TEXT
