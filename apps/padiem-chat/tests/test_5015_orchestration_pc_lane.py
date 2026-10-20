"""#5015: the orchestration surface reuses the existing PC file lane.

A browser turn may reach ``POST /api/orchestration`` instead of the Chat
stream route. The generic bridge call on that surface carries no PC plan and no
selected target, so a PC request could never reach the existing PC lane. These
tests pin that the surface now delegates to the existing PC module, that a
non-PC turn is unchanged, and that no second executor or target store appears.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from app import orchestration_routes as routes
from app.chat_pc_drive import ChatPCDriveError


PC_TEXT = "내 PC의 MeshCentralTrial 폴더에서 파일 목록을 보고, meshcentral-padiem-trial.txt 파일 내용을 읽어줘"
PLAIN_TEXT = "3과 5의 최소공배수를 한 문장으로 답해줘"
DEVICE_ID = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"


class _Lane:
    """The existing PC lane, recorded instead of executed."""

    def __init__(self, outcome=None, error: ChatPCDriveError | None = None) -> None:
        self.outcome = outcome
        self.error = error
        self.calls: list[dict] = []

    async def __call__(self, request, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.outcome


class _Bridge:
    """A ready orchestration bridge with a recorded generic call."""

    ready = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def start(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            conversation_id="chat_generic",
            user_text=kwargs.get("user_text"),
            answer="일반 답변",
            orchestration={"status": "completed"},
            decision_status="completed",
        )


def _install(monkeypatch, lane: _Lane) -> _Bridge:
    import app.chat_pc_drive as chat_pc_drive

    bridge = _Bridge()
    monkeypatch.setattr(chat_pc_drive, "execute_chat_pc_drive_lane", lane)
    # The route's readiness guard requires the concrete bridge contract; this
    # test owns the routing question, so it supplies a ready bridge directly.
    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "owner")
    return bridge


def _request(payload: dict, bridge: _Bridge) -> Request:
    request = Request({
        "type": "http", "method": "POST", "path": "/api/orchestration",
        "headers": [(b"content-type", b"application/json")],
    })
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=bridge,
            history_store=None,
            usage_gate_enforced=False,
            usage_gate=None,
        )
    )
    request._body = json.dumps(payload).encode("utf-8")
    return request


def test_a_pc_turn_is_delegated_to_the_existing_pc_lane(monkeypatch):
    lane = _Lane(outcome=("PC 파일 목록 결과", "chat_pc"))
    bridge = _install(monkeypatch, lane)

    response = asyncio.run(routes.api_orchestration(_request({
        "messages": [{"role": "user", "content": PC_TEXT}],
        "tier": "plus",
        "device_id": DEVICE_ID,
    }, bridge)))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["answer"] == "PC 파일 목록 결과"
    assert body["conversation_id"] == "chat_pc"
    assert body["decision_status"] == "completed"
    # The existing PC module received the server-owned inputs, including the
    # selected target hint, and the generic bridge path did not run.
    assert len(lane.calls) == 1
    call = lane.calls[0]
    assert call["user_text"] == PC_TEXT
    assert call["tier"] == "plus"
    assert call["device_id"] == DEVICE_ID
    assert bridge.calls == []


def test_a_non_pc_turn_keeps_the_ordinary_orchestration_path(monkeypatch):
    lane = _Lane(outcome=None)
    bridge = _install(monkeypatch, lane)

    response = asyncio.run(routes.api_orchestration(_request({
        "messages": [{"role": "user", "content": PLAIN_TEXT}],
    }, bridge)))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["answer"] == "일반 답변"
    # The existing lane is consulted for every turn (it classifies first) and
    # returns None; the generic bridge call then handles the turn unchanged.
    assert len(lane.calls) == 1
    assert len(bridge.calls) == 1


def test_a_pc_lane_refusal_keeps_its_own_code_and_status(monkeypatch):
    lane = _Lane(error=ChatPCDriveError(
        "chat_pc_target_unavailable",
        "선택한 PC의 서버 실행 대상을 확인할 수 없습니다.",
        409,
    ))
    bridge = _install(monkeypatch, lane)

    response = asyncio.run(routes.api_orchestration(_request({
        "messages": [{"role": "user", "content": PC_TEXT}],
    }, bridge)))
    assert response.status_code == 409
    body = json.loads(response.body)
    assert body["error"]["code"] == "chat_pc_target_unavailable"
    assert bridge.calls == []


def test_the_surface_has_no_second_pc_executor_or_target_store():
    source = (
        Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py"
    ).read_text(encoding="utf-8")
    # The delegation reuses the existing module; it does not introduce a new
    # executor, a new authority or a browser-chosen target.
    assert "from .chat_pc_drive import ChatPCDriveError, execute_chat_pc_drive_lane" in source
    assert "agent_plan" not in source
    assert "tool_arguments" not in source