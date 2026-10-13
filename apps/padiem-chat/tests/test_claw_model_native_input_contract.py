"""Claw general AI input follows provider-native size inside explicit HTTP guards.

No live provider, DB, Engine, secret or approval side effects.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest

from app.claw_general_routes import (
    MAX_CLAW_GENERAL_BODY_BYTES,
    P01_ENGINE_REQUEST_ENVELOPE_BYTES,
    _claw_general_user_text,
    _owner_claw_context,
)
from kagent.contracts import ClawTaskIntent, ContractError, ExecutionMode
from kagent.p01_adapter import P01RequestFactory
from kagent.p01_run_flow import create_claw_run


LONG = ("긴 요청과 긴 문맥 " * 4200) + "마지막 끝"  # well beyond 12k; no truncation


def test_general_claw_parser_does_not_reject_old_turn_or_character_caps():
    messages = [
        {"role": "assistant" if i % 2 else "user", "content": f"turn-{i}"}
        for i in range(120)
    ]
    messages.append({"role": "user", "content": LONG})
    text, error = _claw_general_user_text({"messages": messages})
    assert error is None and text == LONG
    assert MAX_CLAW_GENERAL_BODY_BYTES == 6_000_000
    assert P01_ENGINE_REQUEST_ENVELOPE_BYTES == 5_500_000


@pytest.mark.parametrize("messages", [
    [], [{"role": "tool", "content": "x"}],
    [{"role": "user", "content": 10}],
    [{"role": "user", "content": ""}],
])
def test_general_claw_shape_guards_are_unchanged(messages):
    text, response = _claw_general_user_text({"messages": messages})
    assert text is None and response is not None and response.status_code == 400


def test_model_only_claw_long_prompt_reaches_real_p01_execution_request():
    run = create_claw_run("padiem-chat", LONG, model_only_text=True)
    bundle = P01RequestFactory().build(run, selected_model_id="fixture/model")
    assert run.intent.task == LONG
    assert bundle.execution_request.messages[0]["content"] == LONG
    assert bundle.execution_request.agent.allowed_tools == ()
    assert bundle.execution_request.agent.max_steps == 1
    assert bundle.orchestration_request.execution_request.messages[0]["content"] == LONG


def test_other_claw_tasks_keep_12k_and_model_lane_cannot_be_reassigned():
    with pytest.raises(ContractError, match="12000"):
        create_claw_run("some-repo", LONG)
    with pytest.raises(ContractError, match="12000"):
        ClawTaskIntent(
            task_id="task_cloud", task=LONG, repository_ref="padiem-chat",
            source_surface="padiem_claw_general_model_only", execution_mode=ExecutionMode.CLOUD,
        )
    with pytest.raises(ContractError, match="12000"):
        ClawTaskIntent(
            task_id="task_other", task=LONG, repository_ref="external",
            source_surface="padiem_claw_general_model_only",
        )
    with pytest.raises(Exception):
        create_claw_run("external", LONG, model_only_text=True)


def test_claw_owned_saved_history_does_not_silently_keep_only_12_or_4k(monkeypatch):
    import app.claw_general_routes as routes

    class OwnedStore:
        async def get_conversation(self, user_id, conversation_id):
            assert (user_id, conversation_id) == ("owner", "chat_" + "a" * 32)
            return {
                "id": conversation_id,
                "messages": [
                    {"role": "user" if i % 2 == 0 else "assistant",
                     "content": f"saved-{i} " + ("기록" * 200)}
                    for i in range(14)
                ],
            }

    monkeypatch.setattr(routes, "auth_ready", lambda _: True)
    monkeypatch.setattr(routes, "current_user_id", lambda _: "owner")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(history_store=OwnedStore())))
    owned = asyncio.run(_owner_claw_context(request, "chat_" + "a" * 32, "현재 요청"))
    assert "saved-0 " in owned and "saved-13 " in owned
    assert owned.endswith("현재 요청")
    assert len(owned) > 4000


def test_existing_p01_ingress_limit_is_explicit_not_model_token_ceiling():
    source = (Path(__file__).resolve().parents[1] / "app/claw_general_routes.py").read_text(encoding="utf-8")
    assert 'len(model_user_text.encode("utf-8")) > P01_ENGINE_REQUEST_ENVELOPE_BYTES' in source
    assert '"engine_request_envelope_exceeded"' in source


def test_manual_ui_does_not_reapply_independent_4000_character_limit():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    assert 'input.setAttribute("maxlength", "4000")' not in src
    assert "body.length > 4000" not in src
