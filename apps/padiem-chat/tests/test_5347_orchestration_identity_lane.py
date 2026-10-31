"""#5347: the Engine orchestration lane carries the Chat product identity.

In production the PADIEM Chat composer is answered by /api/orchestration, not
by the B14 stream lane. The tier-aware identity instruction added for #5347
lived only in b14_client composition, so the Engine wire carried no product
identity and a live identity question answered with a generic assistant
self-introduction instead of the verified PADIEM Chat grade. These tests pin
the identity on the Engine request, composed from the same Core authority.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from app import orchestration_routes as routes
from app.orchestration_bridge import B62EngineOrchestrationBridge
from padiem_ai_core.dispatch_preinstruction import render_product_identity_instruction

OWNER = "usr_" + "b" * 32
IDENTITY_TEXT = "너 누구야?"


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
            product_identity=fields.get("product_identity"),
        ))
        return SimpleNamespace(
            answer="ok",
            orchestration={"status": "completed"},
            decision_status="completed",
            user_text=fields["user_text"],
            conversation_id=fields["conversation_id"],
        )


class _History:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        return {}

    async def append_exchange(self, user_id, conversation_id, user_text, answer, *, product_scope):
        self.saved.append({"user_text": user_text, "answer": answer})
        return "chat_" + "s" * 32


class _GradeStore:
    def __init__(self, tier: str) -> None:
        self.tier = tier

    async def is_google_admin(self, user_id):
        return False

    async def runtime_access(self, user_id):
        return {"status": "approved", "tier": self.tier}


def _install(monkeypatch, *, grade_tier: str):
    import app.chat_pc_drive as lane

    bridge = _RecordingBridge()
    history = _History()

    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    monkeypatch.setattr(lane, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane, "current_user_id", lambda request: OWNER)
    return bridge, history, _GradeStore(grade_tier)


def _request(payload, history, grade_store):
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/orchestration",
        "headers": [(b"content-type", b"application/json")],
    })
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            history_store=history,
            usage_gate_enforced=False,
            usage_gate=None,
            b66_member_admin_store=grade_store,
            settings=SimpleNamespace(runtime_mode="mock"),
        )
    )
    request._body = json.dumps(payload).encode("utf-8")
    return request


def _payload(tier: str) -> dict:
    return {"messages": [{"role": "user", "content": IDENTITY_TEXT}], "tier": tier}


def test_verified_max_tier_identity_reaches_the_engine_request(monkeypatch) -> None:
    bridge, history, grade_store = _install(monkeypatch, grade_tier="max")

    response = asyncio.run(routes.api_orchestration(
        _request(_payload("max"), history, grade_store),
    ))

    assert response.status_code == 200
    assert len(bridge.requests) == 1
    expected = render_product_identity_instruction("chat", "max")
    assert bridge.requests[0]["agent"]["system_instruction"] == expected


def test_free_tier_identity_reaches_the_engine_request(monkeypatch) -> None:
    bridge, history, grade_store = _install(monkeypatch, grade_tier="free")

    response = asyncio.run(routes.api_orchestration(
        _request(_payload("free"), history, grade_store),
    ))

    assert response.status_code == 200
    expected = render_product_identity_instruction("chat", "free")
    assert bridge.requests[0]["agent"]["system_instruction"] == expected


def test_legacy_request_without_tier_keeps_the_neutral_chat_identity(
    monkeypatch,
) -> None:
    bridge, history, grade_store = _install(monkeypatch, grade_tier="free")

    response = asyncio.run(routes.api_orchestration(
        _request(
            {"messages": [{"role": "user", "content": IDENTITY_TEXT}]},
            history, grade_store,
        ),
    ))

    assert response.status_code == 200
    # No server-verified tier binding: the neutral product identity is carried
    # and no grade is guessed (#5347 owner policy).
    assert bridge.requests[0]["agent"]["system_instruction"] == (
        render_product_identity_instruction("chat", None)
    )
    assert "모드" not in bridge.requests[0]["agent"]["system_instruction"]


def test_skill_instruction_is_preserved_after_the_product_identity(
    monkeypatch,
) -> None:
    bridge, history, grade_store = _install(monkeypatch, grade_tier="max")
    original_build = B62EngineOrchestrationBridge.build_engine_request

    captured: dict = {}

    def _with_skill(**fields):
        fields["skill"] = SimpleNamespace(
            id="writing",
            title="글쓰기",
            description="writing",
            system_instruction="약속된 문체 규칙을 유지한다.",
            task_type="general",
            optimize_for="balanced",
            max_tokens=None,
        )
        request = original_build(**fields)
        captured["request"] = request
        return request

    monkeypatch.setattr(
        B62EngineOrchestrationBridge, "build_engine_request",
        staticmethod(_with_skill),
    )

    response = asyncio.run(routes.api_orchestration(
        _request(_payload("max"), history, grade_store),
    ))

    assert response.status_code == 200
    system_instruction = captured["request"]["agent"]["system_instruction"]
    expected_identity = render_product_identity_instruction("chat", "max")
    assert system_instruction.startswith(expected_identity)
    assert "약속된 문체 규칙을 유지한다." in system_instruction
