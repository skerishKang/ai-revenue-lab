"""#5015/#5573: the orchestration surface and the model-tool PC entry.

A browser turn may reach ``POST /api/orchestration`` instead of the Chat stream
route. The Engine turn this surface starts runs a PC tool *inside* its own run,
so it cannot stage the Chat PC run after the model has chosen a tool — and
staging one per turn would put a pending PC run on ordinary conversation. The
surface therefore defers a PC-capable turn to the Chat stream lane, which is
where the model's tool call is observed before anything is staged or executed.
These tests pin that deferral, that no wording is consulted, that an
ordinary turn is unchanged, and that no second executor or target store appears.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def _install(monkeypatch, lane: _Lane, *, pc_entry: bool = False) -> _Bridge:
    import app.chat_pc_drive as chat_pc_drive

    bridge = _Bridge()
    monkeypatch.setattr(chat_pc_drive, "execute_chat_pc_drive_lane", lane)

    async def _available(request, *, uid, model_id):
        return pc_entry

    monkeypatch.setattr(chat_pc_drive, "pc_tool_entry_available", _available)
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
            settings=SimpleNamespace(runtime_mode="mock"),
        )
    )
    request._body = json.dumps(payload).encode("utf-8")
    return request


def test_a_pc_capable_turn_defers_to_the_chat_stream_lane(monkeypatch):
    """#5573 (3-C-2): the PC decision belongs to the lane that can see it."""
    lane = _Lane(outcome=("PC 파일 목록 결과", "chat_pc"))
    bridge = _install(monkeypatch, lane, pc_entry=True)

    response = asyncio.run(routes.api_orchestration(_request({
        "messages": [{"role": "user", "content": PC_TEXT}],
        "tier": "plus",
        "device_id": DEVICE_ID,
    }, bridge)))
    # The existing browser fallback for a turn this surface does not answer.
    assert response.status_code == 409
    body = json.loads(response.body)
    assert body["error"]["code"] == "orchestration_not_applicable"
    # Nothing ran here: no Engine turn, no PC lane, no browser-chosen target.
    assert bridge.calls == []
    assert lane.calls == []


@pytest.mark.parametrize("text", [PC_TEXT, PLAIN_TEXT])
def test_no_wording_decides_the_deferral(monkeypatch, text):
    """A paraphrase, an ordinary question and a PC sentence defer alike.

    The keyword table is gone, so this surface cannot be selecting PC turns by
    wording in either direction: the server-verified PC plus a tools-declaring
    route decides, and nothing else does.
    """
    lane = _Lane(outcome=None)
    bridge = _install(monkeypatch, lane, pc_entry=True)

    response = asyncio.run(routes.api_orchestration(_request({
        "messages": [{"role": "user", "content": text}],
    }, bridge)))
    assert response.status_code == 409
    assert bridge.calls == []
    assert lane.calls == []


def test_a_non_pc_turn_keeps_the_ordinary_orchestration_path(monkeypatch):
    lane = _Lane(outcome=None)
    bridge = _install(monkeypatch, lane)

    response = asyncio.run(routes.api_orchestration(_request({
        "messages": [{"role": "user", "content": PLAIN_TEXT}],
    }, bridge)))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["answer"] == "일반 답변"
    # No verified PC on a tools route means no deferral and no PC entry: the
    # generic bridge call handles the turn exactly as before.
    assert len(bridge.calls) == 1
    assert lane.calls == []


def test_the_deferral_carries_no_pc_plan_or_target(monkeypatch):
    bridge = _install(monkeypatch, _Lane(outcome=None), pc_entry=True)

    response = asyncio.run(routes.api_orchestration(_request({
        "messages": [{"role": "user", "content": PC_TEXT}],
        "device_id": DEVICE_ID,
        "pc_run_id": "chat_pcq_" + "f" * 32,
    }, bridge)))
    assert response.status_code == 409
    # A browser handle or a browser-selected device is never a plan, a target
    # or an execution grant on this surface.
    assert bridge.calls == []


def test_the_surface_has_no_second_pc_executor_or_target_store():
    source = (
        Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py"
    ).read_text(encoding="utf-8")
    # The surface reads the one existing availability decision and keeps no PC
    # execution path of its own: no lane call, no plan, no target hint, no
    # natural-language table to drift back into a keyword gate.
    assert "from .chat_pc_drive import pc_tool_entry_available" in source
    assert "execute_chat_pc_drive_lane" not in source
    assert "agent_plan" not in source
    assert "tool_arguments" not in source
    assert "_CHAT_PC_MARKERS" not in source
